from dl_portfolio.run import run
from dl_portfolio.logger import LOGGER
from joblib import parallel_backend, Parallel, delayed
import os
from dl_portfolio.constant import LOG_DIR

if __name__ == "__main__":
    import argparse
    from dl_portfolio.config import ae_config

    parser = argparse.ArgumentParser()
    parser.add_argument("--n",
                        default=1,
                        type=int,
                        help="Number of experience to run")
    parser.add_argument("--seed",
                        default=None,
                        type=int,
                        help="Seed")
    parser.add_argument("--verbose",
                        action="store_true",
                        help="increase output verbosity")
    parser.add_argument("--n_jobs",
                        default=1,
                        type=int,
                        help="Number of parallel jobs")
    parser.add_argument("--seeds",
                        nargs="+",
                        default=None,
                        help="List of seeds to run experiments")
    args = parser.parse_args()

    if not os.path.isdir(LOG_DIR):
        os.mkdir(LOG_DIR)

    if args.seeds:
        if args.n_jobs == 1:
            for i, seed in enumerate(args.seeds):
                run(ae_config, seed=int(seed))
        else:
            Parallel(n_jobs=args.n_jobs)(
                delayed(run)(ae_config, seed=int(seed)) for seed in args.seeds
            )

    else:
        if args.n_jobs == 1:
            for i in range(args.n):
                LOGGER.info(f'Starting experiment {i + 1} out of {args.n} experiments')
                if args.seed:
                    run(ae_config, seed=args.seed)
                else:
                    run(ae_config, seed=i)
                LOGGER.info(f'Experiment {i + 1} finished')
                LOGGER.info(f'{args.n - i - 1} experiments to go')
        else:
            if args.seed:
                Parallel(n_jobs=args.n_jobs)(
                    delayed(run)(ae_config, seed=args.seed) for i in range(args.n)
                )
            else:
                Parallel(n_jobs=args.n_jobs)(
                    delayed(run)(ae_config, seed=seed) for seed in range(args.n)
                )