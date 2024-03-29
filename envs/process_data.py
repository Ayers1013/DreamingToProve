import pathlib
import uuid
import datetime
import io
import json

import numpy as np
from gnn import GraphData

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

def flatten_ep(episode):
    _episode={k: v for k,v in episode.items() if not isinstance(v, dict)}
    for key, item in episode.items():
        if key not in _episode.keys():
            _episode.update({key+"/"+nkey: v for nkey,v in flatten_ep(item).items()})

    return _episode

def stack_nest(episode):
    if 'gnn' in episode:
        stacked={}
        for key in episode['gnn'][0].keys():
            stacked[key]=np.array([ep[key] for ep in episode['gnn']])
        episode['gnn']=stacked
    return episode


def save_episodes(directory, episodes):
  directory = pathlib.Path(directory).expanduser()
  directory.mkdir(parents=True, exist_ok=True)
  timestamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
  filenames = []
  for episode in episodes:
    #NOTE transform
    episode=transform_episode(episode)

    identifier = str(uuid.uuid4().hex)
    length = len(episode['reward'])
    filename = directory / f'{timestamp}-{identifier}-{length}.npz'
    with io.BytesIO() as f1:
      episode=flatten_ep(episode)
      np.savez_compressed(f1, **episode)
      f1.seek(0)
      with filename.open('wb') as f2:
        f2.write(f1.read())
    filenames.append(filename)
  return filenames

def process_episode(config, logger, mode, train_eps, eval_eps, episode):
    directory = dict(train=config.traindir, eval=config.evaldir)[mode]
    cache = dict(train=train_eps, eval=eval_eps)[mode]

    #episode=transform_episode(episode)

    filename = save_episodes(directory, [episode])[0]
    length = len(episode['reward']) - 1
    score = float(episode['reward'].astype(np.float64).sum())
    if mode == 'eval':
        cache.clear()
    if mode == 'train' and config.dataset_size:
        total = 0
        for key, ep in reversed(sorted(cache.items(), key=lambda x: x[0])):
            if total <= config.dataset_size - length:
                total += len(ep['reward']) - 1
            else:
                del cache[key]
        logger.scalar('dataset_size', total + length)
    cache[str(filename)] = episode
    print(f'{mode.title()} episode has {length} steps and return {score:.3f}.')
    logger.scalar(f'{mode}_return', score)
    logger.scalar(f'{mode}_length', length)
    logger.scalar(f'{mode}_episodes', len(cache))
    logger.write()

TAG_MODE=True
version=2
#config is not included
def process_episode(config, logger, mode, train_eps, eval_eps, episode):
    directory = dict(train=config.traindir, eval=config.evaldir)[mode]
    cache = dict(train=train_eps, eval=eval_eps)[mode]

    episode=transform_episode_2(episode)

    filename = save_episodes(directory, [episode])[0]
    length = len(episode['reward']) - 1
    score = float(episode['reward'].astype(np.float64).sum())
    if version==2:
      cache.store(episode, str(filename))
    else:
      store(cache, episode, str(filename), TAG_MODE)

    print(f'{mode.title()} episode has {length} steps and return {score:.3f}.')
    logger.scalar(f'{mode}_return', score)
    logger.scalar(f'{mode}_length', length)
    logger.scalar(f'{mode}_episodes', len(cache))
    logger.write()