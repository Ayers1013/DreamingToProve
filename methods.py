from functools import wraps
from tools import Every
import tensorflow as tf

class FunTracker:
  def __init__(self,input_keys, frequency):
    self._input_keys=input_keys
    self._frequency=Every(frequency)
    self.step=1
    self.buffer={key:[] for key in self._input_keys}
    self.buffer['output']=[]
    self.name=""

  def __call__(self,f):
    self.name=f.__name__
    
    @wraps(f)
    def tracked_f(*args,**kwargs):
      if(Every(self.step)):
        for key in self._input_keys:
          try:
            self.buffer[key].append(kwargs[key].copy())
          except:
            self.buffer[key].append(kwargs[key].numpy().copy())

      output=f(*args,**kwargs)
      self.buffer['output'].append(output.numpy().copy())
      self.step+=1

      return output
    return tracked_f

class Tracker:
  def __init__(self):
    self.tracked_funs=[]

  def __call__(self, input_keys=None, frequency=1):
    funTracker=FunTracker(input_keys, frequency)
    self.tracked_funs.append(funTracker)
    return funTracker
  
  def summary(self):
    for fun in self.tracked_funs:
      print(fun.buffer) 


class Method:
  def __init__(self):
    self.useless=True


class Reconstructor(Method):
  def __init__(self, worldModel, track_frequency=0):
    super().__init__()
    self._wm=worldModel
    if(track_frequency):
      self._freq=track_frequency
      self.tracker=Tracker()
      self.encode=self.tracker(input_keys=["input"],frequency=self._freq)(self.encode)
      self.decode=self.tracker(input_keys=["input"],frequency=self._freq)(self.decode)

    
  
  def encode(self, input):
    embed,_=self._wm.encoder(input)
    return embed

  def decode(self, input):
    return self._wm.heads['image'](input).mode()

  def __call__(self, input):
    embed, action_embed=self._wm.encoder(input)
    
    arg_act=tf.math.argmax(input['action'], axis=-1)
    action=tf.gather(action_embed, arg_act)

    post, prior = self._wm.dynamics.observe(embed, action)
    feat = self._wm.dynamics.get_feat(post)
    image=self.decode(input=feat)
    return image

  #@tf.function(experimental_relax_shapes=True)
  def _train(self, data):
    print('Tracing VAE method.')
    data=self._wm.preprocess(data)
    with tf.GradientTape() as model_tape:
      embed, action_embed=self._wm.encoder(data)

      arg_act=tf.math.argmax(data['action'], axis=-1)
      action=tf.gather(action_embed, arg_act)

      post, prior = self._wm.dynamics.observe(embed, action)
      feat = self._wm.dynamics.get_feat(post)
      pred=self._wm.heads['image'](feat)
      like=pred.log_prob(tf.cast(data['image'],tf.float32))
      mse=tf.keras.losses.MeanSquaredError()(data['image'], pred.mode())
      model_loss=-tf.reduce_mean(like)
    model_parts=[self._wm.encoder, self._wm.heads['image']]
    metrics=self._wm._model_opt(model_tape,model_loss, model_parts), mse
    
    return metrics


  def train(self,data_set, epoch):
    for i in range(epoch):
      metrics=self._train(next(data_set))
      if(i%10==0):
        print(metrics)
        self.__call__(next(data_set))

class OneStepLook(Method):
  def __init__(self, worldModel, track_frequency=0):
    super().__init__()
    self._wm=worldModel
    if(track_frequency):
      self._freq=track_frequency
      self.tracker=Tracker()
      self.encode=self.tracker(input_keys=["input"],frequency=self._freq)(self.encode)
      self.decode=self.tracker(input_keys=["input"],frequency=self._freq)(self.decode)


    

        
      
