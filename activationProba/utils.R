library(fGarch)
library(xts)
library(forecast)
library(parallel)
library(doParallel)

# library(POT)
# library(ismev)
# library(MLmetrics)
# source("definition.R")
#library(fExtremes)

get_cv_data = function(dataset, cv, window_size = NULL) {
  # load dataset
  train_data = load_data(path = file.path("data", dataset, cv, "train_linear_activation.csv"), window_size=window_size)
  test_data = load_data(path = file.path("data", dataset, cv, "test_linear_activation.csv"))
  
  return(list(train = train_data, test = test_data))
}

load_data = function(path, end_date = NULL, start_date = NULL, window_size = NULL) {
  data = read.zoo(path, index.column = 1, dec = ".", sep = ",",
                  format = "%Y-%m-%d", read = read.csv)
  data = as.xts(data)
  if (!is.null(end_date)) {
    data = data[index(data) <= end_date,]
  }
  if (!is.null(window_size)) {
    start_date = index(data)[length(index(data)) - window_size + 1]
  }
  if (!is.null(start_date)) {
    data = data[start_date <= index(data),]
  }
  return(data)
}

fit_model = function(data, cond.dist, p = NULL, q = NULL, formula = NULL, arima=TRUE) {
  n = nrow(data)
  # Select mean model
  if (is.null(formula)) {
    if (arima) {
      ARIMAfit = forecast::auto.arima(data, method = "CSS-ML", start.p = 1, start.q = 1, seasonal = FALSE) # stepwise=FALSE, parallel=TRUE, num.cores = parallel::detectCores() - 1)
      arima.order = unname(forecast::arimaorder(ARIMAfit))
      if (arima.order[2] > 0) {
        data = diff(data, lag = 1, differences = arima.order[2], na.pad = FALSE)
        ARIMAfit = forecast::auto.arima(data, method = "CSS-ML", start.p = 1, start.q = 1, seasonal = FALSE)  # stepwise=FALSE, parallel=TRUE, num.cores = parallel::detectCores() - 1)
        arima.order = unname(forecast::arimaorder(ARIMAfit))
      }
      stopifnot(arima.order[2] == 0)
      formula = substitute(~ arma(a, b) + garch(p, q),
                           list(a = arima.order[1], b = arima.order[3], p = p, q = q))
    } else {
      formula = substitute(~ garch(p, q), list(p = p, q = q))
    }
    
  }
  garch.model = tryCatch(
  {
    garch.model = fGarch::garchFit(
      formula = formula,
      data = data,
      cond.dist = cond.dist,
      # algorithm = "lbfgsb",
      trace = FALSE)
    return(list(model = garch.model, aic = garch.model@fit$ics[1]))
  },
    error = function(e)
    {
      message(e)
      return(list(model = NULL, aic = Inf))
    },
    silent = FALSE)
}


model_selection = function(data, model.params, fit_model, parallel = TRUE, arima = TRUE) {
  if (!arima) {
    print("ARIMA is False, center data")
    data.mu = mean(data, na.rm=TRUE)
    data = data - data.mu
  }
  # Normalize data to have variance 1
  data.sd = sd(data)
  data = data / data.sd
  tuning.grid = expand.grid(
    cond.dist = model.params$cond.dist,
    garch.order.p = model.params$garch.order.p,
    garch.order.q = model.params$garch.order.q,
    stringsAsFactors = FALSE
  )

  if (parallel) {
    # Get number of cores
    n.cores = parallel::detectCores() - 1
    #create the cluster
    my.cluster = parallel::makeCluster(
      n.cores
    )
    #register it to be used by %dopar%
    doParallel::registerDoParallel(cl = my.cluster)
    # doParallel::clusterCall(cl = my.cluster, function() source("utils.R"))
    #check if it is registered (optional)
    stopifnot(foreach::getDoParRegistered())
    # How many workers are availalbes ?
    # print(paste(foreach::getDoParWorkers()," workers available"))

    result = foreach(
      cond.dist = tuning.grid$cond.dist,
      garch.order.p = tuning.grid$garch.order.p,
      garch.order.q = tuning.grid$garch.order.q,
      .packages = c("forecast", "fGarch")
    ) %dopar% {

      tryCatch(
        fit_model(data, cond.dist, p = garch.order.p, q = garch.order.q, arima=arima),
        error = function(e) list(model = NULL, aic = Inf),
        silent = FALSE)
    }
    parallel::stopCluster(cl = my.cluster)
  } else {
    result = list()
    for (i in 1:nrow(tuning.grid)) {
      cond.dist = tuning.grid[i, "cond.dist"]
      garch.order.p = tuning.grid[i, "garch.order.p"]
      garch.order.q = tuning.grid[i, "garch.order.q"]
      r = fit_model(data, cond.dist, p = garch.order.p, q = garch.order.q, arima=arima)
      result = append(result, list(r))
    }
  }

  AIC = c()
  for (i in 1:length(result)) {
    AIC = c(AIC, result[[i]]$aic)
  }
  best_model = result[[which.min(AIC)]]$model
  aic = result[[which.min(AIC)]]$aic

  return(list(model = best_model, aic = aic))
}

predict_proba = function(train_data, test_data, window_size, model,
                         fit_model, next_proba, parallel = TRUE, arima = TRUE) {
  if (!arima) {
    print("ARIMA is False")
  }
  formula = model@formula
  cond.dist = model@fit$params$cond.dist

  if (parallel) {
    # Get number of cores
    n.cores = parallel::detectCores() - 1
    #create the cluster
    my.cluster = parallel::makeCluster(
      n.cores
    )
    #register it to be used by %dopar%
    doParallel::registerDoParallel(cl = my.cluster)
    # doParallel::clusterCall(cl = my.cluster, function() source("utils.R"))
    #check if it is registered (optional)
    stopifnot(foreach::getDoParRegistered())
    # How many workers are availalbes ?
    # print(paste(foreach::getDoParWorkers()," workers available"))
    forecasts = foreach(
      i = 1:nrow(test_data),
      .combine = 'rbind',
      .packages = c("forecast", "fGarch")
    ) %dopar% {
      # For first observation in test set, just predict the proba using previously trained model
      if (i == 1) {
        forecast = tryCatch(
          next_proba(model),
          error = function(e) NaN,
          silent = FALSE
        )

      } else {
        # From now, first add the last observed observation
        # Fit new model
        # Predict probability
        temp = rbind(train_data, test_data[1:(i - 1),])
        temp = tail(temp, window_size)
        # Normalize data to have unit variance
        if (!arima) {
          temp = temp - mean(temp, na.rm=TRUE)
        }
        # Normalize data to have variance 1
        temp = temp / sd(temp)
        model = tryCatch(
          fit_model(temp, cond.dist, formula = formula, arima=arima),
          error = function(e) list(model = NULL, aic = Inf),
          silent = FALSE)
        model = model$model
        if (!is.null(model)) {
          forecast = tryCatch(
            next_proba(model),
            error = function(e) NaN,
            silent = FALSE
          )
        } else {
          forecast = NaN
        }
      }
      forecast
    }
    parallel::stopCluster(cl = my.cluster)
  } else {
    forecasts = c()
    for (i in 1:nrow(test_data)) {
      if (i == 1) {
        if (!is.null(model)) {
          forecast = next_proba(model)
        } else {
          forecast = NaN
        }
      } else {
        temp = rbind(train_data, test_data[1:(i - 1),])
        temp = tail(temp, window_size)
        # Normalize data to have unit variance
        if (!arima) {
          temp = temp - mean(temp, na.rm=TRUE)
        }
        temp = temp / sd(temp)
        model = fit_model(temp, cond.dist, formula = formula, arima=arima)
        model = model$model
        if (!is.null(model)) {
          forecast = next_proba(model)
        } else {
          forecast = NaN
        }
      }
      forecasts = rbind(forecasts, forecast)
    }
  }
  # probas = xts(probas, order.by = index(test_data))
  # colnames(probas) = "proba"
  forecasts = data.frame(forecasts)
  colnames(forecasts) = c("proba", "meanForecast", "meanError", "sdForecast")
  rownames(forecasts) = 1:nrow(forecasts)
  return(forecasts)
}

prediction_conf = function(object, conf = 0.95) {
  cond.dist = object@fit$params$cond.dist
  # Get conf interval:
  # https://rdrr.io/cran/fGarch/src/R/methods-predict.R
  if (cond.dist == "norm") {
    crit_valu = qnorm(1 - (1 - conf) / 2)
    crit_vald = qnorm((1 - conf) / 2)
  }
  if (cond.dist == "snorm") {
    crit_valu = qsnorm(1 - (1 - conf) / 2, xi = coef(object)["skew"])
    crit_vald = qsnorm((1 - conf) / 2, xi = coef(object)["skew"])
  }
  if (cond.dist == "std") {
    crit_valu = fGarch::qstd(1 - (1 - conf) / 2, nu = coef(object)["shape"])
    crit_vald = fGarch::qstd((1 - conf) / 2, nu = coef(object)["shape"])
  }
  if (cond.dist == "sstd") {
    crit_valu = fGarch::qsstd(1 - (1 - conf) / 2, nu = coef(object)["shape"],
                              xi = coef(object)["skew"])
    crit_vald = fGarch::qsstd((1 - conf) / 2, nu = coef(object)["shape"],
                              xi = coef(object)["skew"])
  }
  if (cond.dist == "QMLE") {
    e = sort(object@residuals / object@sigma.t)
    crit_valu = e[round(t * (1 - (1 - conf) / 2))]
    crit_vald = e[round(t * (1 - conf) / 2)]
  }
  int_l = meanForecast + crit_vald * meanError
  int_u = meanForecast + crit_valu * meanError
  
  return (list(int_u=int_u, int_l=int_l))
}

next_proba = function(object, conf = 0.95) {
  cond.dist = object@fit$params$cond.dist
  # Predict next value
  model.forecast = fGarch::predict(object = object, n.ahead = 1, conf = conf)
  meanForecast = model.forecast$meanForecast # conditional mean from mean model
  meanError = model.forecast$meanError # Error
  sdForecast = model.forecast$standardDeviation # conditional volatility

  # Calculate proba
  Z_hat = -meanForecast / sdForecast
  if (cond.dist == "norm") {
    proba = pnorm(Z_hat)
  }
  if (cond.dist == "snorm") {
    proba = psnorm(Z_hat)
  }
  if (cond.dist == "std") {
    proba = fGarch::pstd(Z_hat)
  }
  if (cond.dist == "sstd") {
    proba = fGarch::psstd(Z_hat)
  }
  
  return (c(proba, meanForecast, meanError, sdForecast))
}

get_dist_functon = function(dist) {
  if (dist == "norm") {
    func = pnorm
  }
  if (dist == "snorm") {
    func = psnorm
  }
  if (dist == "std") {
    func = fGarch::pstd
  }
  if (dist == "sstd") {
    func = fGarch::psstd
  }

  return(func)
}