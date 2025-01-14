import argparse
import numpy as np
import itertools
import tqdm

import jax

from metaaf.data import NumpyLoader
from metaaf.meta import MetaAFTrainer
import metaaf.optimizer_lms as lms
import metaaf.optimizer_nlms as nlms
import metaaf.optimizer_rmsprop as rms
import metaaf.optimizer_rls as rls
import zoo.aec.optimizer_kf as kf
from metaaf.callbacks import CheckpointCallback

import zoo.aec.aec as aec

"""
ID
python aec_baselines.py --n_frames 1 --window_size 2048 --hop_size 1024 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name id_lms --optimizer lms --random_roll --dataset linear --true_rir_len 1024

python aec_baselines.py --n_frames 1 --window_size 2048 --hop_size 1024 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name id_rms --optimizer rms --random_roll --dataset linear --true_rir_len 1024

python aec_baselines.py --n_frames 1 --window_size 2048 --hop_size 1024 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name id_nlms --optimizer nlms --random_roll --dataset linear --true_rir_len 1024

python aec_baselines.py --n_frames 1 --window_size 2048 --hop_size 1024 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name id_rls --optimizer rls --optimize_conjugate --random_roll --dataset linear --true_rir_len 1024

Universal AEC
python aec_baselines.py --n_frames 4 --window_size 1024 --hop_size 512 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name aec_combo_lms_mdf --optimizer lms --random_level --random_roll --dataset combo

python aec_baselines.py --n_frames 4 --window_size 1024 --hop_size 512 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name aec_combo_nlms_mdf --optimizer nlms --random_level --random_roll --dataset combo

python aec_baselines.py --n_frames 4 --window_size 1024 --hop_size 512 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name aec_combo_rms_mdf --optimizer rms --random_level --random_roll --dataset combo

python aec_baselines.py --n_frames 4 --window_size 1024 --hop_size 512 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name aec_combo_rls_mdf --optimizer rls --optimize_conjugate --random_level --random_roll --dataset combo

python aec_baselines.py --n_frames 4 --window_size 1024 --hop_size 512 --n_in_chan 1 --n_out_chan 1 --is_real --batch_size 32 --total_epochs 0 --n_devices 1 --name aec_combo_kf_mdf --optimizer kf --random_level --random_roll --dataset combo
"""
if __name__ == "__main__":
    import pprint

    parser = argparse.ArgumentParser()
    parser.add_argument("--optimizer", type=str, default="lms")

    # get the optimizer package
    optimizer_type = parser.parse_known_args()[0].optimizer
    if optimizer_type == "lms":
        optimizer_pkg = lms
    elif optimizer_type == "nlms":
        optimizer_pkg = nlms
    elif optimizer_type == "rms":
        optimizer_pkg = rms
    elif optimizer_type == "rls":
        optimizer_pkg = rls
    elif optimizer_type == "kf":
        optimizer_pkg = kf
    # load its arguments
    parser = optimizer_pkg.add_args(parser)

    # get everything else
    parser.add_argument("--name", type=str, default="")
    parser.add_argument("--double_talk", action="store_true")
    parser.add_argument("--scene_change", action="store_true")
    parser.add_argument("--random_roll", action="store_true")
    parser.add_argument("--random_level", action="store_true")
    parser.add_argument("--dataset", type=str, default="linear")
    parser.add_argument("--true_rir_len", type=int, default=None)

    parser = aec.AECOLS.add_args(parser)
    parser = MetaAFTrainer.add_args(parser)
    kwargs = vars(parser.parse_args())
    pprint.pprint(kwargs)

    if kwargs["dataset"] == "linear":
        aec_dataset = aec.MSFTAECDataset_RIR
        dset_kwargs = {
            "double_talk": kwargs["double_talk"],
            "scene_change": kwargs["scene_change"],
            "random_roll": kwargs["random_roll"],
            "random_level": kwargs["random_level"],
            "rir_len": kwargs["true_rir_len"],
        }
    elif kwargs["dataset"] == "nonlinear":
        aec_dataset = aec.MSFTAECDataset
        dset_kwargs = {
            "double_talk": kwargs["double_talk"],
            "scene_change": kwargs["scene_change"],
            "random_roll": kwargs["random_roll"],
            "random_level": kwargs["random_level"],
        }
    elif kwargs["dataset"] == "combo":
        aec_dataset = aec.ComboAECDataset
        dset_kwargs = {
            "random_roll": kwargs["random_roll"],
            "random_level": kwargs["random_level"],
        }

    # make the dataloders
    val_loader = NumpyLoader(
        aec_dataset(
            mode="val",
            **dset_kwargs,
        ),
        batch_size=kwargs["batch_size"],
        num_workers=4,
    )
    test_loader = NumpyLoader(
        aec_dataset(
            mode="test",
            **dset_kwargs,
        ),
        batch_size=kwargs["batch_size"],
        num_workers=0,
    )

    system = MetaAFTrainer(
        _filter_fwd=aec._AECOLS_fwd,
        filter_kwargs=aec.AECOLS.grab_args(kwargs),
        filter_loss=aec.aec_loss,
        train_loader=val_loader,
        val_loader=val_loader,
        test_loader=test_loader,
        _optimizer_fwd=optimizer_pkg._fwd,
        optimizer_kwargs=optimizer_pkg.grab_args(kwargs),
        meta_val_loss=aec.neg_erle_val_loss,
        init_optimizer=optimizer_pkg.init_optimizer,
        make_mapped_optmizer=optimizer_pkg.make_mapped_optmizer,
        kwargs=kwargs,
    )

    # epochs set to zero, this is just an initialization
    key = jax.random.PRNGKey(0)
    outer_learned, losses = system.train(**MetaAFTrainer.grab_args(kwargs), key=key)

    # now run the actual val loop
    tuning_options = optimizer_pkg.get_tuning_options(**optimizer_pkg.grab_args(kwargs))
    pprint.pprint(tuning_options)
    all_configs = list(itertools.product(*list(tuning_options.values())))

    # holder for best config
    best_config = dict(zip(list(tuning_options.keys()), all_configs[0]))
    best_val_scores = np.array([np.inf])

    # final holder
    mean_val_scores = []

    for config in tqdm.tqdm(all_configs):
        config_dict = dict(zip(list(tuning_options.keys()), config))
        outer_learned["optimizer_p"].update(config_dict)
        val_loss = system.val_loop(outer_learnable=outer_learned)

        mean_val_scores.append(np.nanmean(val_loss))

        if np.nanmean(val_loss) < np.nanmean(best_val_scores):
            best_config = config_dict
            best_val_scores = val_loss

    for i in range(len(all_configs)):
        print(f"CFG: {all_configs[i]} -- {mean_val_scores[i]}")

    # run test and save the best parameters
    outer_learned["optimizer_p"].update(best_config)
    print(f"BEST -- CFG: {best_config} -- {np.median(best_val_scores)} --")

    test_loss = system.test_loop(outer_learnable=outer_learned)

    # print results without nans and percent nan
    percent_nan = np.isnan(test_loss).mean()
    print(
        f"Mean Test:{np.nanmean(test_loss)} - Median Test:{np.nanmedian(test_loss)} - % NAN {percent_nan}"
    )

    # save this model in the metaaf format
    ckpt_cb = CheckpointCallback(name=kwargs["name"], ckpt_base_dir="./meta_ckpts")
    ckpt_cb.on_init(
        system.inner_fixed, system.outer_fixed, system.kwargs, outer_learned
    )
    ckpt_cb.on_train_epoch_end(
        best_val_scores,
        best_val_scores,
        outer_learned,
        0,
    )
