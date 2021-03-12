import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json
from sklearn import preprocessing
import tensorflow as tf
from tensorflow.keras import backend as K
from dl_portfolio.custom_layer import DenseTied, TransposeDense
from dl_portfolio.constraints import WeightsOrthogonalityConstraint, NonNegAndUnitNorm, UncorrelatedFeaturesConstraint
from typing import List
from dl_portfolio.logger import LOGGER
import tensorflow as tf
import datetime as dt
import os
import seaborn as sns

LOG_DIR = 'dl_portfolio/log_AE'


def heat_map_cluster(load_dir, show=False, save=False):
    sets = os.listdir(load_dir)
    sets.sort(key=lambda x: int(x))
    encoder_weights = {}
    for set_ in sets:
        encoder_weights[int(set_)] = pd.read_pickle(f"{load_dir}/{set_}/encoder_weights.p")

    n_sets = len(encoder_weights.keys())
    fig, axs = plt.subplots(n_sets, 3, figsize=(10, 10 * n_sets), sharey=True)
    yticks = list(encoder_weights[n_sets - 1].index)

    for i, s in enumerate(encoder_weights.keys()):
        print(i)
        for j, c in enumerate(list(encoder_weights[s].columns)):
            ax = sns.heatmap(encoder_weights[s][c].values.reshape(-1, 1),
                             xticklabels=[c],
                             yticklabels=yticks,
                             vmin=0., vmax=1., ax=axs[i, j], cbar=j == 2)
    if save:
        plt.savefig(f'{load_dir}/clusters_heatmap.png', bbox_inches='tight', pad_inches=0)
    if show:
        plt.show()


def get_layer_by_name(name, model):
    return [l for l in model.layers if l.name == name][0]


class NonNegAndUnitNormInit(tf.keras.initializers.Initializer):

    def __init__(self, initializer: str, **kwargs):
        if initializer == 'glorot_uniform':
            self.initializer = tf.keras.initializers.GlorotUniform()
        elif initializer == 'random_normal':
            self.initializer = tf.keras.initializers.RandomNormal(mean=kwargs.get('mean', 0.0),
                                                                  stddev=kwargs.get('stddev', 0.05))
        else:
            raise NotImplementedError()

    def __call__(self, shape, dtype=None, **kwargs):
        values = self.initializer(shape=shape, dtype=dtype, **kwargs)
        values = NonNegAndUnitNorm(axis=0)(values)
        return values

    def get_config(self):  # To support serialization
        return {"initializer": self.initializer}


def pca_ae_model(input_dim: int, encoding_dim: int, activation: str = 'linear',
                 kernel_initializer: str = 'glorot_uniform',
                 ortho_weights: bool = True,
                 non_neg_unit_norm: bool = True,
                 uncorr_features: bool = True,
                 activity_regularizer=None,
                 non_neg=False,
                 **kwargs
                 ):
    kernel_regularizer = WeightsOrthogonalityConstraint(encoding_dim, axis=0) if ortho_weights else None
    if non_neg_unit_norm:
        assert not non_neg
        kernel_constraint = NonNegAndUnitNorm(axis=0)
    elif non_neg:
        kernel_constraint = tf.keras.constraints.NonNeg()
    else:
        kernel_constraint = None
    if activity_regularizer is None:
        weightage = kwargs.get('weightage', 1.)
        activity_regularizer = UncorrelatedFeaturesConstraint(encoding_dim,
                                                              weightage=weightage) if uncorr_features else None
    else:
        assert not uncorr_features

    input_ = tf.keras.layers.Input(input_dim, dtype=tf.float32, name='input')
    encoder_layer_1 = tf.keras.layers.Dense(encoding_dim,
                                            activation=activation,
                                            kernel_initializer=kernel_initializer,
                                            kernel_regularizer=kernel_regularizer,
                                            activity_regularizer=activity_regularizer,
                                            kernel_constraint=kernel_constraint,
                                            use_bias=True,
                                            name='encoder_1',
                                            dtype=tf.float32)
    # encoder_layer_2 = tf.keras.layers.Dense(encoding_dim,
    #                                         activation=activation,
    #                                         kernel_initializer=kernel_initializer,
    #                                         kernel_regularizer=kernel_regularizer,
    #                                         activity_regularizer=activity_regularizer,
    #                                         kernel_constraint=kernel_constraint,
    #                                         use_bias=True,
    #                                         name='encoder_2',
    #                                         dtype=tf.float32)

    decoder_layer_1 = DenseTied(input_dim,
                                tied_to=encoder_layer_1,
                                activation=activation,
                                kernel_initializer=kernel_initializer,
                                kernel_regularizer=kernel_regularizer,
                                use_bias=True,
                                dtype=tf.float32,
                                name='decoder_1')
    # decoder_layer_2 = TransposeDense(int(0.75 * input_dim), encoder_layer_2, activation=activation,
    #                                  kernel_initializer=kernel_initializer,
    #                                  kernel_regularizer=kernel_regularizer,
    #                                  use_bias=True,
    #                                  dtype=tf.float32,
    #                                  name='decoder_2')
    # decoder_layer_1 = TransposeDense(input_dim, encoder_layer_1, activation=activation,
    #                                  kernel_initializer=kernel_initializer,
    #                                  kernel_regularizer=kernel_regularizer,
    #                                  use_bias=True,
    #                                  dtype=tf.float32,
    #                                  name='decoder_1')
    output = decoder_layer_1(encoder_layer_1(input_))
    # output = decoder_layer_1(
    #     decoder_layer_2(
    #         encoder_layer_2(
    #             encoder_layer_1(input_)
    #         )
    #     )
    # )

    # encoding = encoder_layer_2(
    #     encoder_layer_1(input_)
    # )
    encoding = encoder_layer_1(input_)
    autoencoder = tf.keras.models.Model(input_, output)
    encoder = tf.keras.models.Model(input_, encoding)

    return autoencoder, encoder


def get_features(data, start: str, end: str, assets: List, val_size=30 * 6, rescale=None):
    if end == str(data.index[-1]):
        end = '2020-03-08 00:00:00'
    else:
        end = pd.to_datetime(end) + dt.timedelta(days=6 * 30)
    train_data = data.loc[start:end, assets].iloc[:-1, :]
    train_data = train_data.loc[:, pd.IndexSlice[:, 'price']].droplevel(1, 1)

    val_data = data.loc[end:, assets]
    val_data = val_data.loc[:, pd.IndexSlice[:, 'price']].droplevel(1, 1)
    val_data = val_data.iloc[:val_size]

    test_data = data.loc[val_data.index[-1]:, assets].iloc[1:]
    test_data = test_data.loc[:, pd.IndexSlice[:, 'price']].droplevel(1, 1)
    test_data = test_data.iloc[:val_size]

    # featurization
    train_data = train_data.pct_change(1).dropna()
    train_dates = train_data.index
    train_data = train_data.values
    val_data = val_data.pct_change(1).dropna()
    val_dates = val_data.index
    val_data = val_data.values
    test_data = test_data.pct_change(1).dropna()
    test_dates = test_data.index
    test_data = test_data.values

    # standardization
    scaler = preprocessing.StandardScaler(with_std=True, with_mean=False)
    scaler.fit(train_data)
    train_data = scaler.transform(train_data)
    val_data = scaler.transform(val_data)
    test_data = scaler.transform(test_data)

    if rescale is not None:
        train_data = train_data * rescale
        val_data = val_data * rescale
        test_data = test_data * rescale

    dates = {
        'train': train_dates,
        'val': val_dates,
        'test': test_dates
    }
    return train_data, val_data, test_data, scaler, dates


if __name__ == "__main__":
    seed = np.random.randint(100)
    # seed = 200
    np.random.seed(seed)
    LOGGER.info(f"Set seed: {seed}")
    save = False
    model_name = f'linear_simple_{seed}_uncorr_lr_e-3_l1_reg'
    seq_len = 5
    learning_rate = 1e-3
    epochs = 1
    batch_size = 64
    activation = 'linear'
    encoding_dim = 3
    val_size = 30 * 6
    uncorr_features = False
    weightage = 1e-1
    activity_regularizer = tf.keras.regularizers.l1(1e-3)
    loss = 'mse'
    rescale = None
    kernel_initializer = NonNegAndUnitNormInit(initializer='glorot_uniform')
    ortho_weights = True
    non_neg_unit_norm = True
    non_neg = False

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor='val_rmse', min_delta=1e-4, patience=300, verbose=1,
            mode='min', baseline=None, restore_best_weights=True
        )
    ]

    if save:
        subdir = dt.datetime.strftime(dt.datetime.now(), '%Y%m%d-%H%M%S')
        if model_name is not None and model_name != '':
            subdir = subdir + '_' + model_name
        save_dir = f"{LOG_DIR}/{subdir}"
        os.mkdir(save_dir)

    # Load data
    data_specs = json.load(open('./data/crypto_data/coingecko/data_spec_coins_selected.json', 'r'))
    data = pd.read_csv('./data/crypto_data/coingecko/coins_selected.csv', index_col=0, header=[0, 1])
    data = data.astype(np.float32)
    data.index = pd.to_datetime(data.index)

    asset_to_train_on = {}
    for set_ in data_specs:
        LOGGER.info(f'Starting with set: {set_}')
        if save:
            os.mkdir(f"{save_dir}/{set_}")
        data_spec = data_specs[set_]
        if int(set_) > 0:
            prev_set = str(int(set_) - 1)
            assets = asset_to_train_on[prev_set].copy()
            assets = assets + data_spec['assets']
        else:
            assets = data_spec['assets'].copy()
        asset_to_train_on[set_] = assets

        train_data, val_data, test_data, scaler, dates = get_features(data, data_spec['start'], data_spec['end'],
                                                                      assets,
                                                                      val_size=val_size, rescale=rescale)
        # Build model
        input_dim = len(assets)
        model, encoder = pca_ae_model(input_dim, encoding_dim, activation=activation,
                                      kernel_initializer=kernel_initializer,
                                      ortho_weights=ortho_weights,
                                      non_neg_unit_norm=non_neg_unit_norm,
                                      uncorr_features=uncorr_features,
                                      activity_regularizer=activity_regularizer,
                                      non_neg=non_neg,
                                      weightage=weightage
                                      )

        print(model.summary())

        if int(set_) > 0:
            LOGGER.info('Set weights')
            # Set encoder layer weights
            weights = model.layers[1].get_weights()[0]
            weights[:-1] = prev_encoder_weights[0]
            bias = prev_encoder_weights[1]
            model.layers[1].set_weights([weights, bias])
            encoder.layers[1].set_weights([weights, bias])

            # Set decoder layer weights
            bias = model.layers[2].get_weights()[0]
            bias[:-1] = prev_decoder_weights[0]
            model.layers[2].set_weights([bias, weights, model.layers[2].get_weights()[-1]])

        # Train
        LOGGER.info('Start training')
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),  # Very low learning rate
                      loss=tf.keras.losses.MeanSquaredError(),
                      metrics=[tf.keras.metrics.MeanSquaredError(name='mse'),
                               tf.keras.metrics.RootMeanSquaredError(name='rmse')]
                      )
        history = model.fit(train_data, train_data,
                            epochs=epochs,
                            batch_size=batch_size,
                            validation_data=(val_data, val_data),
                            validation_batch_size=batch_size,
                            callbacks=callbacks,
                            shuffle=False,
                            verbose=1)
        if save:
            model.save(f"{save_dir}/{set_}/model.h5")
        prev_encoder_weights = model.layers[1].get_weights()
        prev_decoder_weights = model.layers[2].get_weights()

        fix, axs = plt.subplots(1, 3, figsize=(15, 5))
        axs[0].plot(history.history['loss'], label='loss')
        axs[0].plot(history.history['val_loss'], label='val loss')
        axs[0].legend()
        axs[1].plot(history.history['mse'], label='mse')
        axs[1].plot(history.history['val_mse'], label='val_mse')
        axs[1].legend()
        axs[2].plot(history.history['rmse'], label='rmse')
        axs[2].plot(history.history['val_rmse'], label='val_rmse')
        axs[2].legend()
        if save:
            plt.savefig(f"{save_dir}/{set_}/history.png")
        plt.show()

        # Evaluate
        model.evaluate(train_data, train_data)
        model.evaluate(val_data, val_data)

        val_prediction = model.predict(val_data)
        val_prediction = pd.DataFrame(val_prediction, columns=assets, index=dates['val'])
        encoder_weights = pd.DataFrame(prev_encoder_weights[0], index=assets)

        test_prediction = model.predict(test_data)
        test_prediction = pd.DataFrame(test_prediction, columns=assets, index=dates['test'])

        if save:
            val_prediction.to_pickle(f"{save_dir}/{set_}/val_prediction.p")
            test_prediction.to_pickle(f"{save_dir}/{set_}/test_prediction.p")
            encoder_weights.to_pickle(f"{save_dir}/{set_}/encoder_weights.p")

        # indices = np.random.choice(list(range(len(val_data))), 5).tolist()
        # xticks = assets
        # for i in indices:
        #     plt.figure()
        #     plt.scatter(xticks, val_data[i], label='truth')
        #     plt.scatter(xticks, val_prediction.values[i], label='prediction')
        #     plt.legend()
        #     plt.show()

        # for i in range(input_dim):
        #     rmse = np.sqrt(np.mean((val_prediction.values[:, i] - val_data[:, i]) ** 2))
        #     print(assets[i], rmse)

        # val_features = encoder.predict(val_data)
        # print(np.corrcoef(val_features.T))
        # print(encoder.layers[-1].kernel.numpy().sum(0))

    if save:
        heat_map_cluster(save_dir, show=True, save=save)
