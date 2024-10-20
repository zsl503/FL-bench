from argparse import ArgumentParser, Namespace
from copy import deepcopy
from typing import Any

import torch

from src.server.fedavg import FedAvgServer
from src.client.pfedme import pFedMeClient
from src.utils.tools import NestedNamespace


class pFedMeServer(FedAvgServer):

    @staticmethod
    def get_hyperparams(args_list=None) -> Namespace:
        parser = ArgumentParser()
        parser.add_argument("--beta", type=float, default=1.0)
        parser.add_argument("--lamda", type=float, default=15)
        parser.add_argument("--pers_lr", type=float, default=0.01)
        parser.add_argument("--mu", type=float, default=1e-3)
        parser.add_argument("--k", type=int, default=5)
        return parser.parse_args(args_list)

    def __init__(
        self,
        args: NestedNamespace,
        algo: str = "pFedMe",
        unique_model=False,
        use_fedavg_client_cls=False,
        return_diff=False,
    ):
        super().__init__(args, algo, unique_model, use_fedavg_client_cls, return_diff)
        self.clients_personalized_model_params = {
            i: deepcopy(self.model.state_dict()) for i in self.train_clients
        }
        self.init_trainer(pFedMeClient)

    def package(self, client_id: int):
        server_package = super().package(client_id)
        server_package["personalized_model_params"] = (
            self.clients_personalized_model_params[client_id]
        )
        return server_package

    @torch.no_grad()
    def aggregate(self, clients_package: dict[int, dict[str, Any]]):
        clients_weight = [package["weight"] for package in clients_package.values()]
        clients_local_model_params = [
            package["local_model_params"] for package in clients_package.values()
        ]
        weights = torch.tensor(clients_weight) / sum(clients_weight)
        aggregated_params = [
            torch.sum(weights * torch.stack(params, dim=-1), dim=-1)
            for params in zip(*clients_local_model_params)
        ]
        for param_prev, param_new in zip(
            self.public_model_params.values(), aggregated_params
        ):
            param_prev.data = (
                1 - self.args.pfedme.beta
            ) * param_prev + self.args.pfedme.beta * param_new
