import tensorflow as tf
import numpy as np
from tensorflow.python.util.nest import flatten
#from gnn.tf_helpers import *
from collections.abc import Iterable

# class encapsulating tf.segment_sum etc. offering basic functionalities

#elements of tf_helpers
def mean_or_zero(data):
    return tf.cond(
        tf.equal(tf.size(data), 0),
        lambda: 0.,
        lambda: tf.reduce_mean(data),
    )

#lens: shape=(), dtype=tf.int32 
class Segments(tf.Module):
    def __init__(self, nonzero = False):
        super().__init__()
        self.nonzero_guarantee = nonzero

    def __call__(self, lens):
        nonzero=self.nonzero_guarantee

        if nonzero: assertions = [tf.debugging.assert_less(0, lens)]
        else: assertions = []
        with tf.name_scope("segments") as scope:
            with tf.control_dependencies(assertions):

                self.lens = lens
                self.start_indices = tf.cumsum(self.lens, exclusive = True)
                self.segment_num = tf.size(self.lens)

                if nonzero:
                    self.nonzero_indices = tf.range(self.segment_num)
                    self.nonzero_lens = self.lens
                    self.nonzero_num = self.segment_num
                    self.start_indices_nonzero = self.start_indices
                else:
                    mask = tf.greater(self.lens, 0)
                    self.nonzero_indices = tf.boolean_mask(
                        tf.range(self.segment_num), mask
                    )
                    self.nonzero_lens = tf.boolean_mask(self.lens, mask)
                    self.nonzero_num = tf.size(self.nonzero_lens)
                    self.start_indices_nonzero = tf.cumsum(self.nonzero_lens, exclusive = True)

                self.empty = tf.equal(self.nonzero_num, 0)
                self.data_len = tf.reduce_sum(self.nonzero_lens)

                def scatter_empty():
                    return tf.zeros([0], dtype=tf.int32)
                def scatter_nonempty():
                    return tf.scatter_nd(
                        tf.expand_dims(self.start_indices_nonzero[1:], 1),
                        tf.ones([self.nonzero_num-1], dtype=tf.int32),
                        [self.data_len],
                    )
                scattered = tf.cond(self.empty, scatter_empty, scatter_nonempty)

                self.segment_indices_nonzero = tf.cumsum(scattered)
                #self.segment_indices_nonzero=tf.reshape(self.segment_indices_nonzero, [None,])

                if nonzero: self.segment_indices = self.segment_indices_nonzero
                else:
                    self.segment_indices = self.fill_nonzero(
                        tf.boolean_mask(tf.range(self.segment_num), mask),
                    )

    def fill(self, constants):
        return tf.gather(constants, self.segment_indices)
    
    def fill_nonzero(self, constants):
        return tf.gather(constants, self.segment_indices_nonzero)

    def collapse_nonzero(self, data, operations = [tf.math.segment_max, tf.math.segment_sum]):

        with tf.name_scope("collapse_nonzero") as scope:
            res = [
                op(data, self.segment_indices_nonzero)
                for op in operations
            ]
            if len(res) == 1: return res[0]
            else: return tf.concat(res, -1)

    def add_zeros(self, data):

        if self.nonzero_guarantee: return data

        with tf.name_scope("add_zeros") as scope:
            out_dim = [self.segment_num] + data.shape.dims[1:]
            return tf.scatter_nd(
                tf.expand_dims(self.nonzero_indices, 1),
                data, out_dim,
            )

    def collapse(self, data, *args, **kwargs):

        x = self.collapse_nonzero(data, *args, **kwargs)
        #x=data
        x = self.add_zeros(x)
        return x

    def mask_segments(self, data, mask, nonzero = False):

        if self.nonzero_guarantee: nonzero = True

        with tf.name_scope("mask_segments") as scope:
            mask = tf.cast(mask, bool)
            data_mask = self.fill(mask)
            masked_lens = tf.boolean_mask(self.lens, mask)
            masked_data = tf.boolean_mask(data, data_mask)
            return Segments(masked_lens, nonzero), masked_data

    def mask_data(self, data, mask, nonzero = False):

        if nonzero: assert(self.nonzero_guarantee)

        with tf.name_scope("mask_data") as scope:
            new_lens = self.segment_sum(tf.cast(mask, tf.int32))
            new_data = tf.boolean_mask(data, tf.cast(mask, bool))
            return Segments(new_lens, nonzero), new_data

    def partition_segments(self, data, partitions, num_parts, nonzero = False):

        if self.nonzero_guarantee: nonzero = True
        if not isinstance(nonzero, Iterable):
            nonzero = [nonzero]*num_parts

        with tf.name_scope("partition_segments") as scope:
            data_parts = self.fill(partitions)
            parted_lens = tf.dynamic_partition(self.lens, partitions, num_parts)
            parted_data = tf.dynamic_partition(data, data_parts, num_parts)
            return [
                (Segments(lens, nzg), parted_data_part)
                for lens, parted_data_part, nzg in zip(parted_lens, parted_data, nonzero)
            ]

    def segment_sum_nonzero(self, data):
        return tf.math.segment_sum(data, self.segment_indices_nonzero)

    def segment_sum(self, data):
        if self.nonzero_guarantee:
            return self.segment_sum_nonzero(data)
        else:
            return tf.unsorted_segment_sum(
                data = data,
                segment_ids = self.segment_indices,
                num_segments = self.segment_num,
            )

    def log_softmax(self, logits):
        with tf.name_scope("segments.log_softmax") as scope:
            # numeric stability
            offset = tf.math.segment_max(logits, self.segment_indices_nonzero)
            logits_stab = logits - self.fill_nonzero(offset)
            # softmax denominators
            sums_e = self.fill_nonzero(
                self.segment_sum_nonzero(tf.exp(logits_stab)),
            )
            return logits_stab - tf.math.log(sums_e)

    def gather_nonzero(self, data, indices):

        with tf.name_scope("segments.gather") as scope:
            with tf.control_dependencies([tf.compat.v1.assert_non_negative(indices),
                                          tf.compat.v1.assert_less(indices, self.nonzero_lens)]):

                return tf.gather(data, self.start_indices_nonzero + indices)

    def gather(self, data, indices):

        assert(self.nonzero_guarantee)
        return self.gather_nonzero(data, indices)

    def cumsum_ex(self, data):
        all_cumsum = tf.cumsum(data, exclusive = True)
        seg_cumsum = tf.gather(all_cumsum, self.start_indices_nonzero)
        return all_cumsum - self.fill_nonzero(seg_cumsum)

    def sample_nonzero(self, probs):
        x = self.segment_sum(
            tf.cast(dtype = tf.int32, x=tf.greater_equal(
                self.fill_nonzero(tf.random.uniform([self.nonzero_num])),
                self.cumsum_ex(probs),
            ))
        )
        x = tf.maximum(0, x-1)
        return x

    def sample(self, probs):
        assert(self.nonzero_guarantee)
        return self.sample_nonzero(probs)

    def argmax_nonzero(self, data):
        max_vals = tf.math.segment_max(data, self.segment_indices_nonzero)
        is_max = tf.equal(self.fill_nonzero(max_vals), data)
        not_after_max = tf.equal(0, self.cumsum_ex(tf.cast(is_max, tf.int32)))
        return self.segment_sum_nonzero(tf.cast(not_after_max, tf.int32)) - 1

    def argmax(self, data):
        assert(self.nonzero_guarantee)
        return self.argmax_nonzero(data)

    def sparse_cross_entropy(self, log_probs, labels, weights = None, aggregate = mean_or_zero):
        result = self.gather(-log_probs, labels)
        if weights is not None: result = result * weights
        if aggregate: result = aggregate(result)
        return result

    def cross_entropy(self, log_probs, target_probs, aggregate = mean_or_zero):
        result = -self.segment_sum(log_probs * target_probs)
        if aggregate: result = aggregate(result)
        return result

    def entropy(self, probs = None, log_probs = None, aggregate = mean_or_zero):
        assert(probs is not None or log_probs is not None)
        if probs is None: probs = tf.exp(log_probs)
        elif log_probs is None:
            log_probs = tf.where(tf.greater(probs, 0), tf.math.log(probs),
                                 tf.zeros_like(probs))
        return self.cross_entropy(log_probs, probs, aggregate)

    def kl_divergence(self, log_probs, target_probs, aggregate = mean_or_zero):
        return self.cross_entropy(log_probs, target_probs, aggregate) \
            - self.entropy(probs = target_probs, aggregate = aggregate)

#data:shape=(None,)+self.data_shape, dtype=
class SegmentsPH(Segments):
    def __init__(self, dtype = tf.int32, nonzero = False):

        Segments.__init__(self, nonzero = nonzero)
        

    def __call__(self, lens):
        #It will be asserted in the parent class
        #if self.nonzero_guarantee: assert(0 not in lens)

        super().__call__(lens)