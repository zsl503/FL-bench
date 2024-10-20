from argparse import ArgumentParser, Namespace

import torch
import numpy as np
from sklearn.cluster import AgglomerativeClustering

from src.server.fedavg import FedAvgServer
from src.utils.tools import vectorize, NestedNamespace


class CFLServer(FedAvgServer):

    @staticmethod
    def get_hyperparams(args_list=None) -> Namespace:
        parser = ArgumentParser()
        parser.add_argument("--eps_1", type=float, default=0.4)
        parser.add_argument("--eps_2", type=float, default=1.6)
        parser.add_argument("--min_cluster_size", type=int, default=2)
        parser.add_argument("--start_clustering_round", type=int, default=20)
        return parser.parse_args(args_list)

    def __init__(
        self,
        args: NestedNamespace,
        algo: str = "CFL",
        unique_model=True,
        use_fedavg_client_cls=True,
        return_diff=True,
    ):
        super().__init__(args, algo, unique_model, use_fedavg_client_cls, return_diff)
        assert (
            len(self.train_clients) == self.client_num
        ), "CFL doesn't support `User` type split."

        self.clients_model_params_diff = [None for _ in self.train_clients]
        self.similarity_matrix = np.eye(len(self.train_clients))
        self.client_clusters = [list(range(len(self.train_clients)))]

    def train_one_round(self):
        clients_package = self.trainer.train()

        for client_id in self.selected_clients:
            self.clients_model_params_diff[client_id] = [
                -clients_package[client_id]["model_params_diff"][key]
                for key in self.clients_personal_model_params[client_id].keys()
            ]

        self.compute_pairwise_similarity()
        client_clusters_new = []
        for indices in self.client_clusters:
            max_norm = compute_max_diff_norm(
                [self.clients_model_params_diff[i] for i in indices]
            )
            mean_norm = compute_mean_diff_norm(
                [self.clients_model_params_diff[i] for i in indices]
            )

            if (
                mean_norm < self.args.cfl.eps_1
                and max_norm > self.args.cfl.eps_2
                and len(indices) > self.args.cfl.min_cluster_size
                and self.current_epoch >= self.args.cfl.start_clustering_round
            ):
                cluster_1, cluster_2 = self.cluster_clients(
                    self.similarity_matrix[indices][:, indices]
                )
                client_clusters_new += [cluster_1, cluster_2]

            else:
                client_clusters_new += [indices]

        self.client_clusters = client_clusters_new
        self.aggregate_clusterwise()

    @torch.no_grad()
    def compute_pairwise_similarity(self):
        self.similarity_matrix = np.eye(len(self.train_clients))
        for i, diff_a in enumerate(self.clients_model_params_diff):
            for j, diff_b in enumerate(self.clients_model_params_diff[i + 1 :], i + 1):
                if diff_a is not None and diff_b is not None:
                    score = torch.cosine_similarity(
                        vectorize(diff_a), vectorize(diff_b), dim=0, eps=1e-12
                    ).item()
                    self.similarity_matrix[i, j] = score
                    self.similarity_matrix[j, i] = score

    def cluster_clients(self, similarities):
        clustering = AgglomerativeClustering(
            metric="precomputed", linkage="complete"
        ).fit(-similarities)

        cluster_1 = np.argwhere(clustering.labels_ == 0).flatten()
        cluster_2 = np.argwhere(clustering.labels_ == 1).flatten()
        return cluster_1, cluster_2

    @torch.no_grad()
    def aggregate_clusterwise(self):
        for cluster in self.client_clusters:
            model_params_diff_list = [
                self.clients_model_params_diff[i]
                for i in cluster
                if self.clients_model_params_diff[i] is not None
            ]
            weights = torch.ones(len(model_params_diff_list)) * (
                1 / len(model_params_diff_list)
            )
            aggregated_diff = [
                torch.sum(torch.stack(diff, dim=-1) * weights, dim=-1)
                for diff in zip(*model_params_diff_list)
            ]
            for i in cluster:
                for (name, param), diff in zip(
                    self.clients_personal_model_params[i].items(), aggregated_diff
                ):
                    param.data += diff.to(param.dtype)

        self.clients_model_params_diff = [None for _ in self.train_clients]


@torch.no_grad()
def compute_max_diff_norm(model_params_diff: list[list[torch.Tensor]]):
    flag = False
    for diff in model_params_diff:
        if diff is not None:
            flag = True
            break
    if flag:
        return max(
            [
                vectorize(diff).norm().item()
                for diff in model_params_diff
                if diff is not None
            ]
        )
    return 0


@torch.no_grad()
def compute_mean_diff_norm(model_params_diff: list[list[torch.Tensor]]):
    flag = False
    for diff in model_params_diff:
        if diff is not None:
            flag = True
            break
    if flag:
        return (
            torch.stack(
                [vectorize(diff) for diff in model_params_diff if diff is not None]
            )
            .mean(dim=0)
            .norm()
            .item()
        )
    return 0
