import pathlib
from sys import version
import uuid
import datetime
import io
import json

import numpy as np
from gnn import GraphData

from gnn.graph_data import GraphData
import pathlib

import numpy as np
from dataset.data_storage import DataStorage, DataSampler

'We need to import envs.ProLog.meta_data to collect meta for new environments.'
from envs.ProLog import meta_data

class TokenParser:
  'Parse tokens to ints. Note that 1 is reserved for padding.'
  __slots__ = ['voc', '_cache', '_count', '_path']
  def __init__(self, path='envs/ProLog_tokens'):
    self._path=path+'.txt'
    self.voc = {}
    self._cache = {}
    self.load()

  def load(self):
    file = open(self._path, 'r')
    for i, line in enumerate(file):
      'line ends with \n'
      line=line[:-1]
      self.voc[line]=i+1
    self._count = len(self.voc)+1
    file.close()

  def add_token(self, token):
    self.voc[token]=self._count
    self._cache[token]=self._count
    self._count+=1
    return self._count-1

  def parse(self, token_string):
    tokens = token_string.split(' ')
    res = []
    for t in tokens:
      if t in self.voc:
        res.append(self.voc[t])
      else:
        res.append(self.add_token(t))
    return res

  def __del__(self):
    'Upon destructing the class, it saves the new tokens to the file'
    if(len(self._cache)==0): return
    file = open(self._path, 'a')
    for k in self._cache.keys():
        file.write(k+'\n')
    file.close()

def transform_episode(episode):
    if 'gnn' in episode.keys():
        gnn_input=episode['gnn']
        graphs=[GraphData().load_from_dict(g) for g in gnn_input]

        d={
            'num_nodes':np.array([len(e['ini_nodes']) for e in gnn_input]),
            'num_symbols':np.array([len(e['ini_symbols']) for e in gnn_input]),
            'num_clauses':np.array([len(e['ini_clauses']) for e in gnn_input])
        }

        data = GraphData.ini_list()
        for g in graphs: data.append(g)
        data.flatten()

        d.update(data.convert_to_dict())

        episode['gnn']=d

    else: return episode

    if 'action_space' in episode.keys():
        gnn_input=episode['action_space']

        e=gnn_input
        d={
            'num_nodes':np.array([len(e['ini_nodes'])]),
            'num_symbols':np.array([len(e['ini_symbols'])]),
            'num_clauses':np.array([len(e['ini_clauses'])])
        }
        episode['action_space'].update(d)
    return episode

def transform_episode_2(episode):
  def indexing(d):
    d={i: e for i, e in enumerate(d)}
  if 'gnn' in episode.keys(): indexing(episode['gnn'])
  else: return episode

  if False and 'action_space' in episode.keys():
    episode['action_space']=episode['action_space'][0]

  return episode

def flatten_ep(episode):
    _episode={k: v for k,v in episode.items() if not isinstance(v, dict)}
    for key, item in episode.items():
        if key not in _episode.keys():
            _episode.update({key+"/"+nkey: v for nkey,v in flatten_ep(item).items()})

    return _episode

def deflatten(episode):
  _episode={k:v for k,v in episode.items() if k.find('/')==-1}
  for k,v in episode.items():
    per=k.find('/')
    if per!=-1:
      key=k[:per]
      if key not in _episode.keys():
        _episode[key]={}
      _episode[key][k[per+1:]]=v
    
  return _episode


def save_episodes(directory, episodes):
  directory = pathlib.Path(directory).expanduser()
  directory.mkdir(parents=True, exist_ok=True)
  timestamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
  filenames = []
  meta = None
  for episode in episodes:

    identifier = str(uuid.uuid4().hex)
    length = len(episode['reward'])
    problem_name=episode['problem_name']
    #filename = directory / f'{timestamp}-{identifier}-{length}.npz'
    fileplace = directory /f'{problem_name}'
    if not fileplace.exists():
      fileplace.mkdir(parents=True, exist_ok=False)
      problem_file = problem_name.replace('__', '/')+'.p'

      #TODO this code should be moved to envs
      meta=meta_data(problem_file)
      
      with io.BytesIO() as f1:
        np.savez_compressed(f1, **meta)
        f1.seek(0)
        with (fileplace/'_meta.npz').open('wb') as f2:
          f2.write(f1.read()) 
    filename = fileplace/ f'{problem_name}-{timestamp}-{identifier}-{length}.npz'
    del episode['problem_name']
    with io.BytesIO() as f1:
      episode=flatten_ep(episode)
      np.savez_compressed(f1, **episode)
      f1.seek(0)
      with filename.open('wb') as f2:
        f2.write(f1.read())
    filenames.append(filename)
  return filenames, meta

def store(storage, episode, ep_name, tag=False):
  if not tag: storage[ep_name]=episode
  else:
    problem_name, _, _, length=ep_name[:-4].split("-")
    length=int(length)
    if problem_name not in storage: storage[problem_name]={}
    x=storage[problem_name]
    if length not in x: x[length]={}
    x=x[length]
    x[ep_name]=episode

TAG_MODE=True
version=2
#config is not included
def process_episode(config, logger, mode, train_eps, eval_eps, episode):
    directory = dict(train=config.traindir, eval=config.evaldir)[mode]
    cache = dict(train=train_eps, eval=eval_eps)[mode]

    episode=transform_episode_2(episode)

    filenames, meta = save_episodes(directory, [episode])
    filename = filenames[0]
    length = len(episode['reward']) - 1
    # TODO This modificatioon wasn't here
    score = float(np.array(episode['reward']).astype(np.float64).sum())
    #score = float(episode['reward'].astype(np.float64).sum())
    if version==2:
      cache.store(episode, str(filename))
      if meta: cache._meta[str(filename)] = meta
    else:
      store(cache, episode, str(filename), TAG_MODE)

    print(f'{mode.title()} episode has {length} steps and return {score:.3f}.')
    logger.scalar(f'{mode}_return', score)
    logger.scalar(f'{mode}_length', length)
    logger.scalar(f'{mode}_episodes', len(cache))
    logger.write()

#NOTE allow_pickle=True
def load_episodes(directory, limit=None):
  directory = pathlib.Path(directory).expanduser()
  if version==2:
    episodes = DataSampler()  # dep: DataStorage()
  else:
    episodes = {}
  total = 0
  for problem in directory.glob('*/'):
    filename = problem / '_meta.npz'
    with filename.open('rb') as f:
        meta = np.load(f,allow_pickle=True)
        meta = {k: meta[k] for k in meta.keys()}
    episodes._meta[str(problem)]=meta
    for i, filename in enumerate(sorted(problem.glob('*.npz'))):
      if i==0: continue
      try:
        with filename.open('rb') as f:
          episode = np.load(f,allow_pickle=True)
          episode = {k: episode[k] for k in episode.keys()}
          episode = deflatten(episode)
      except Exception as e:
        print(f'Could not load episode: {e}')
        continue 
      if version==2:
        episodes.store(episode, str(filename))
      else:
        store(episodes, episode, str(filename), TAG_MODE)
      
      total += len(episode['reward']) - 1
      if limit and total >= limit:
        break
  return episodes