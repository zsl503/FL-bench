from argparse import ArgumentParser, Namespace

from src.server.fedavg import FedAvgServer
from src.client.lgfedavg import LGFedAvgClient
from src.utils.tools import NestedNamespace


class LGFedAvgServer(FedAvgServer):

    @staticmethod
    def get_hyperparams(args_list=None) -> Namespace:
        parser = ArgumentParser()
        parser.add_argument("--num_global_layers", type=int, default=1)
        return parser.parse_args(args_list)

    def __init__(
        self,
        args: NestedNamespace,
        algo: str = "LG-FedAvg",
        unique_model=False,
        use_fedavg_client_cls=False,
        return_diff=False,
    ):
        super().__init__(args, algo, unique_model, use_fedavg_client_cls, return_diff)
        self.init_trainer(LGFedAvgClient)
