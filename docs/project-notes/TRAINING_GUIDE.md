# Training Guide with Time Estimates

## What's Fixed

✅ **Epoch/Iteration Output**: Models now show progress every 100 iterations/epochs
✅ **Training Time Tracking**: Shows how long each model takes to train
✅ **Total Time Summary**: Shows combined training time at the end
✅ **Progress Messages**: Clear indication of what's being trained

---

## Training Time Estimates

### For Your Hardware (RTX 3050)

#### **CPU Baseline Training** (`python scripts/train_models.py`)
- **Score Model** (HistGradientBoosting, 250 iterations): **1-2 minutes**
  - Epochs shown every iteration with progress bar
- **Win Model** (HistGradientBoosting, 250 iterations + 3-fold calibration): **2-3 minutes**
  - Epochs shown every iteration
- **Total**: **3-5 minutes**

#### **GPU Model Comparison** (`python scripts/train_gpu_best.py`)
- **CatBoost Score** (3000 iterations, GPU): **2-5 minutes**
  - Shows iteration numbers every 100 steps
- **XGBoost Score** (2500 estimators, GPU): **2-4 minutes**
  - Shows tree building progress
- **CatBoost Win** (2500 iterations, GPU): **2-4 minutes**
  - Shows iteration numbers every 100 steps
- **XGBoost Win** (2000 estimators, GPU): **1-3 minutes**
  - Shows tree building progress
- **Ensemble + Evaluation**: **1 minute**
- **Total**: **8-20 minutes** (depending on GPU availability and data size)

---

## Example Output

### CPU Baseline Training

```
############################################################
#                                                          #
#  IPL PREDICTION: CPU BASELINE MODEL TRAINING            #
#                                                          #
############################################################

Loaded 34,450 training samples

============================================================
TRAINING SCORE MODEL (HistGradientBoostingRegressor)
============================================================
Training data: 28,850 rows
Test data: 5,600 rows
Features: 45

Starting model training (max 250 iterations)...
Iteration 1/250
Iteration 2/250
Iteration 3/250
... (progress continues) ...
Iteration 250/250

✓ Training completed in 1.23 seconds

Score Model Performance:
  MAE:  18.47 runs
  RMSE: 25.01 runs

✓ Model saved to models/score_model.pkl

============================================================
TRAINING WIN PROBABILITY MODEL (HistGradientBoostingClassifier)
============================================================
Training data: 28,050 rows
Test data: 5,200 rows
Features: 45

Starting model training (max 250 iterations with 3-fold calibration)...
Iteration 1/250
Iteration 2/250
... (progress continues) ...
Iteration 250/250

✓ Training completed in 2.15 seconds

Win Model Performance:
  Accuracy: 70.1%
  Log Loss: 0.5470
  Brier Score: 0.1860

✓ Model saved to models/win_model.pkl

============================================================
FINAL SUMMARY
============================================================

Score Model Training Time: 1.23 seconds
Win Model Training Time:   2.15 seconds

Total Training Time:       3.38 seconds (0.06 minutes)

✓ All models trained successfully!
============================================================
```

### GPU Model Comparison

```
############################################################
#                                                          #
#  IPL PREDICTION: GPU MODEL COMPARISON TRAINING          #
#                                                          #
############################################################

Loaded 34,450 total samples
Score training: 28,850 samples
Win training: 28,050 samples

============================================================
TRAINING MODELS
============================================================

Score Models:
  Training CatBoost Score model (3000 iterations)...
  0:	learn: 150.4521	test: 157.8234
  100:	learn: 45.2314	test: 48.9123
  200:	learn: 32.1456	test: 35.7234
  300:	learn: 25.3214	test: 28.1234
  ... (continues every 100 iterations) ...
  2400:	learn: 18.1234	test: 24.5123
  Stopped by early_stopping
  
    ✓ Completed in 3.45s

  Training XGBoost Score model (2500 estimators)...
  [0]	validation_0-rmse:165.12345
  [100]	validation_0-rmse:48.23456
  ... (continues) ...
  
    ✓ Completed in 2.87s

Win Probability Models:
  Training CatBoost Win model (2500 iterations)...
  0:	learn: 0.6834	test: 0.6921
  100:	learn: 0.5234	test: 0.5456
  ... (continues every 100 iterations) ...
  
    ✓ Completed in 2.54s

  Training XGBoost Win model (2000 estimators)...
  [0]	validation_0-logloss:0.68234
  [100]	validation_0-logloss:0.52345
  ... (continues) ...
  
    ✓ Completed in 1.67s

============================================================
EVALUATING MODELS
============================================================

 Best Score Model: CATBOOST
   Validation RMSE: 24.51
   Test RMSE: 26.78

 Best Win Model: CATBOOST
   Validation Log Loss: 0.5234
   Test Log Loss: 0.5412

✓ Best models saved to production

============================================================
FINAL SUMMARY
============================================================
Total Training Time: 10.53 seconds (0.18 minutes)
✓ Report saved to models/gpu_model_report.json
============================================================
```

---

## Understanding the Output

### CPU Models
- **"Iteration X/Y"** - Shows progress of HistGradientBoosting training
- Each message indicates one epoch/iteration completed
- You'll see 250 iterations for score, then 250 for win

### GPU Models (CatBoost)
- **"0: learn: X test: Y"** - Iteration 0, learning loss and test loss
- **"100: learn: X test: Y"** - Iteration 100 (shown every 100 iterations)
- Numbers on left = iteration number
- "learn:" = training loss
- "test:" = validation loss (should decrease)
- "Stopped by early_stopping" = Training stopped early because validation loss stopped improving

### GPU Models (XGBoost)
- **"[0] validation_0-rmse: X"** - Tree 0, validation RMSE
- **"[100] validation_0-rmse: Y"** - Tree 100
- You'll see ~2000-2500 lines of progress

---

## How to Run Training

### Option 1: Just CPU Baseline (Fast - ~3 minutes)
```powershell
python scripts/train_models.py
```

### Option 2: Just GPU Comparison (GPU required - ~10-20 minutes)
```powershell
python scripts/train_gpu_best.py
```

### Option 3: Full Pipeline (Both - ~15-25 minutes total)
```powershell
# First do baseline
python scripts/train_models.py

# Then do GPU comparison
python scripts/train_gpu_best.py
```

---

## What's Happening During Training

### Preprocessing Phase (~30 seconds)
- Loading CSV files
- Splitting data by season
- OneHot encoding categorical features

### Training Phase (varies by model)
- Model learns patterns from data
- Shows progress every N iterations
- Validates on test data
- Early stopping if no improvement

### Evaluation Phase (~1 minute)
- Computing metrics (RMSE, Log Loss, Accuracy, etc.)
- Comparing models
- Saving best models to disk

---

## Optimization Tips

### Make Training Faster
1. **Reduce iterations** (edit scripts):
   - Change `max_iter=250` to `max_iter=100` in train_models.py
   - Change `iterations=3000` to `iterations=1000` in CatBoost calls

2. **Reduce validation set**:
   - Change `early_stopping_rounds=150` to `early_stopping_rounds=50`

3. **Use GPU only**:
   - Skip `train_models.py`, just run `train_gpu_best.py`

### Make Training More Thorough
1. **Increase iterations**:
   - Change to `max_iter=500` for CPU models
   - Change to `iterations=5000` for CatBoost

2. **More cross-validation**:
   - Change `cv=3` to `cv=5` in CalibratedClassifierCV

---

## Monitoring Progress

While training runs, you'll see:
- ✅ Iterations/epochs counting up
- ✅ Loss values decreasing (good sign)
- ✅ Validation metrics improving
- ✅ "Early stopping" message (training stopped when no improvement)
- ✅ Final metrics and elapsed time

---

## Troubleshooting

### Issue: "GPU not available, falling back to CPU"
- **Cause**: CatBoost/XGBoost can't find GPU
- **Solution**: Training will use CPU instead (slower but still works)
- **Time**: Will take 2-3x longer

### Issue: Training takes longer than expected
- **Cause**: Large dataset or many iterations
- **Solution**: Use fewer iterations or reduce dataset size
- **Expected**: First run is usually slower due to data processing

### Issue: No progress shown
- **Cause**: Verbose settings are off
- **Solution**: Already fixed! You should see progress now
- **Check**: Models show output every 100 iterations

---

## Next Steps

1. **Test with CPU baseline** (fast, 3 minutes):
   ```powershell
   python scripts/train_models.py
   ```

2. **Test with GPU comparison** (if GPU available, 10-20 minutes):
   ```powershell
   python scripts/train_gpu_best.py
   ```

3. **Watch the output** to see epochs/iterations progress
4. **Check final metrics** to verify models are trained
5. **Always saves best models** to `models/score_model.pkl` and `models/win_model.pkl`

---

## Final Notes

✅ You can now see **exactly** which epoch/iteration is being trained
✅ **Training time** is displayed after each model and total
✅ **GPU fallback** to CPU if needed (with notification)
✅ **Early stopping** prevents overfitting by stopping when validation loss stops improving
✅ Models auto-save when training completes

**Expected Total Time for Full Pipeline: 15-30 minutes** ⏱️
