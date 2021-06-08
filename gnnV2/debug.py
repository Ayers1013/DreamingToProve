from gnn.segments import *
from gnn.graph_input import *
from gnn.graph_data import GraphData
data=GraphData()
data.load_from_str("1 1 1 1 1 1 1 1 0 1 0 1,0 1 2 3 4 3 1 0 3 3,-1 -1 -1 -1 -1 -1 2 -1 -1 -1 4 -1 -1 -1 -1 -1 8 -1 10 -1,-1 1 1 -1 1 1 -1 1 1 -1;0 0 1 0 1 0 0 0 1 0 1 0,3 3 3 3,3 -1 5 -1 9 -1 11 -1,-1 1 1 -1;0 0 0 0 0 0 0 0 0 0 0 0,,,;2 2 1 4 1,0 -1 -1 7 -1 -1 1 -1 -1 6 -1 -1 2 -1 -1 3 2 -1 5 4 -1 9 8 -1 11 10 -1 4 -1 -1,-1 1 1 -1 1 -1 1 1 -1 1;2 2 0 1 0 1 2 1 0 1 0 1,0 1 2 4 2 3 3 5 4 4 5;1 1 2 2 3 2,0 0 1 3 5 6 7 1 9 6 11;0 0 1 0 1 0 0 0 3 0 3 0;1 1 0 1 0;0 1 3 3 3 3;0 0 0 0 0 0 1 0 0 0 0")
from gnn.network import GraphNetwork
from tools import Optimizer

#data=str(data)


gnet=GraphNetwork()
print(gnet([data]))

opt=Optimizer('gnn', lr=1e-2, wd=0)


def train(x):
    
    with tf.GradientTape() as tape:
        y=gnet(x)
        loss=tf.reduce_sum(y)
    return opt(tape,loss,[gnet])

for _ in range(20):
    train([data])


print(gnet([data]))

gnet.save("anakin")

gnet2=GraphNetwork()
gnet2([data])
gnet2.load("anakin")

print(gnet2([data]))