import tensorflow as tf
import tensorflow.keras.layers as tfkl
from tensorflow.keras.layers import Layer
from misc import Module, Model
from .utils import *

def scaled_dot_product_attention(q, k, v, mask):
    matmul_qk = tf.matmul(q, k, transpose_b=True)  # (..., seq_len_q, seq_len_k)

    # scale matmul_qk
    dk = tf.cast(tf.shape(k)[-1], tf.float32)
    scaled_attention_logits = matmul_qk / tf.math.sqrt(dk)

    # add the mask to the scaled tensor.
    if mask is not None:
        scaled_attention_logits += (mask * -1e9)

    # softmax is normalized on the last axis (seq_len_k) so that the scores
    # add up to 1.
    attention_weights = tf.nn.softmax(scaled_attention_logits, axis=-1)  # (..., seq_len_q, seq_len_k)

    output = tf.matmul(attention_weights, v) # (..., seq_len_q, depth_v)

    return output, attention_weights

PRE_LAYER_NORM = True
class MultiHeadAttention(Module):
  @property
  def _param_args(self):
      return ['d_model', 'num_heads']
  
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    assert self._d_model % self._num_heads == 0

    self._depth = self._d_model // self._num_heads

    self.wq = tfkl.Dense(self._d_model)
    self.wk = tfkl.Dense(self._d_model)
    self.wv = tfkl.Dense(self._d_model)

    self.dense = tfkl.Dense(self._d_model)

    if PRE_LAYER_NORM:
        self.layerNorms_v = tfkl.LayerNormalization()
        self.layerNorms_k = tfkl.LayerNormalization()
        self.layerNorms_q = tfkl.LayerNormalization()

  def split_heads(self, x, batch_size):
    """Split the last dimension into (num_heads, depth).
    Transpose the result such that the shape is (batch_size, num_heads, seq_len, depth)
    """
    x = tf.reshape(x, (batch_size, -1, self._num_heads, self._depth))
    return tf.transpose(x, perm=[0, 2, 1, 3])

  def call(self, v, k, q, mask=None):
    #Normalize input
    if PRE_LAYER_NORM:
        v = self.layerNorms_v(v)
        k = self.layerNorms_k(k)
        q = self.layerNorms_q(q)

    #To support calculations when batxh_size_q=1
    batch_size_q = tf.shape(q)[0]
    batch_size_kv = tf.shape(k)[0]

    q = self.wq(q)  # (batch_size, seq_len, d_model)
    k = self.wk(k)  # (batch_size, seq_len, d_model)
    v = self.wv(v)  # (batch_size, seq_len, d_model)

    q = self.split_heads(q, batch_size_q)  # (batch_size, num_heads, seq_len_q, depth)
    k = self.split_heads(k, batch_size_kv)  # (batch_size, num_heads, seq_len_k, depth)
    v = self.split_heads(v, batch_size_kv)  # (batch_size, num_heads, seq_len_v, depth)

    # scaled_attention.shape == (batch_size, num_heads, seq_len_q, depth)
    # attention_weights.shape == (batch_size, num_heads, seq_len_q, seq_len_k)
    scaled_attention, attention_weights = scaled_dot_product_attention(
        q, k, v, mask)

    scaled_attention = tf.transpose(scaled_attention, perm=[0, 2, 1, 3])  # (batch_size, seq_len_q, num_heads, depth)

    concat_attention = tf.reshape(scaled_attention,
                                  (batch_size_kv, -1, self._d_model))  # (batch_size, seq_len_q, d_model)

    output = self.dense(concat_attention)  # (batch_size, seq_len_q, d_model)

    #log useful metrics
    self.log_matrix_analytics(attention_weights, 'attention_matrix')
    
    return output, attention_weights

class MLP(Module):
    @property
    def _param_args(self):
        return ['d_model', 'dff']

    @property
    def _param_default(self):
        return dict(rate=0.04)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dense = tfkl.Dense(self._dff, activation='relu')  # (batch_size, seq_len, dff)
        self.dense2 = tfkl.Dense(self._d_model)  # (batch_size, seq_len, d_model)
        self.dropout = tfkl.Dropout(self._rate)
        self.layernorm = tfkl.LayerNormalization()
        self.dropout2 = tfkl.Dropout(self._rate)
        self.dropout3 = tfkl.Dropout(self._rate)

    def call(self, inp, training):
        x = self.dropout(inp, training)
        x = self.layernorm(x)
        
        x = self.dense(x)
        x = self.dropout(x, training)
        x = self.dense2(x)

        x = self.dropout3(x, training)
        
        return x + inp

class CrossAttention(Module):
    @property
    def _param_args(self):
        return ['d_model', 'num_heads', 'dff', 'rate']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.mha_v = self.configure(MultiHeadAttention)
        self.mha_q = self.configure(MultiHeadAttention)

        self.mlp_v = self.configure(MLP)
        self.mlp_q = self.configure(MLP)

    def call(self, v, q, mask, training):
        'mask:  (batch_size, len_q, len_v)'

        _v, att_v = self.mha_v(q, q, v, mask)
        v = _v + v
        v = self.mlp_v(v, training)

        if mask is not None: mask = tf.transpose(mask, (0, 1, 3, 2))
        _q, att_q = self.mha_q(v, v, q, mask)
        q = _q + q
        q = self.mlp_q(q, training)

        return v, q, (att_v, att_q)

class SelfAttention(Module):
    @property
    def _param_args(self):
        return ['d_model', 'num_heads', 'dff', 'rate']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mha = self.configure(MultiHeadAttention)
        self.mlp = self.configure(MLP)

    def call(self, x, mask, training):

        _x, _att = self.mha(x, x, x, mask)
        x = _x + x
        x = self.mlp(x, training)

        return x, _att

class ConditionedAttention(Module):
    @property
    def _param_args(self):
        return ['d_model', 'num_heads', 'dff', 'rate']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mha = self.configure(MultiHeadAttention)
        self.mlp = self.configure(MLP)

    def call(self, v, q, mask, training):
        
        if mask is not None: mask = tf.transpose(mask, (0, 1, 3, 2))
        _q, _att = self.mha(v, v, q, mask)
        q = _q + q
        q = self.mlp(q, training)

        return q, _att

class Attention(Module):
    @property
    def _param_args(self):
        return ['d_model', 'num_heads', 'dff', 'rate']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mha1 = self.configure(MultiHeadAttention)
        self.mha2 = self.configure(MultiHeadAttention)
        self.mlp1 = self.configure(MLP)
        self.mlp2 = self.configure(MLP)

    def call(self, x, y, mask, look_ahead_mask, training):
        
        _x, _ = self.mha1(x, x, x, look_ahead_mask)
        x = _x + x
        x = self.mlp1(x, training)

        _x, _ = self.mha2(y, y, x, mask)
        x = _x + x
        x = self.mlp2(x, training)

        return x, y

class DeepCrossAttention(CrossAttention):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        #self.satt_v = SelfAttention(d_model, num_heads, dff, rate)
        self.satt_q = self.configure(SelfAttention)

    def call(self, v, q, mask, training):

        v, q, att = super().call(v, q, mask, training)
        q, _att = self.satt_q(q, None, training)

        return v, q, att