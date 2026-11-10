# Requirement 2: five measures against known answers

| measure | rows | pass | fail | recorded | verdict |
|---|---:|---:|---:|---:|---|
| grid lock | 12 | 9 | 0 | 3 | PASSES within tolerance |
| kick body (decay20_ms, decay40_ms) | 12 | 0 | 12 | 0 | **FAILS**, and the bias is frequency dependent |
| sustain share | 5 | 5 | 0 | 0 | PASSES exactly |
| band shares | 12 | 4 | 0 | 8 | PASSES off the edges; edge tones split three ways |
| crest | 9 | 5 | 0 | 4 | PASSES under clipping; padding drift is the window rule |

## kick body: decay40_ms under-reads, worse at lower frequency

Three columns on purpose. The analytic truth is exp(-decay t). The envelope reference is an independent analytic-signal envelope on the same samples, which shows what ANY envelope method costs. The library is `hits_extra.decay40_ms`.

| f0 Hz | decay | analytic ms | envelope ref ms | library ms | envelope err % | library err % |
|---:|---:|---:|---:|---:|---:|---:|
| 40 | 10 | 460.5 | 455.1 | 294.0 | -1.2 | -35.4 |
| 40 | 25 | 184.2 | 164.5 | 120.0 | -10.7 | -27.0 |
| 40 | 50 | 92.1 | 68.6 | 58.0 | -25.5 | -15.4 |
| 40 | 100 | 46.1 | 168.6 | 32.0 | +266.1 | -81.0 |
| 50 | 10 | 460.5 | 448.9 | 306.0 | -2.5 | -31.8 |
| 50 | 25 | 184.2 | 170.5 | 136.0 | -7.4 | -20.2 |
| 50 | 50 | 92.1 | 73.6 | 76.0 | -20.1 | +3.3 |
| 50 | 100 | 46.1 | 35.5 | 36.0 | -22.9 | +1.4 |
| 60 | 10 | 460.5 | 453.6 | 346.0 | -1.5 | -23.7 |
| 60 | 25 | 184.2 | 174.7 | 146.0 | -5.2 | -16.4 |
| 60 | 50 | 92.1 | 77.3 | 72.0 | -16.1 | -6.9 |
| 60 | 100 | 46.1 | 108.5 | 38.0 | +135.6 | -65.0 |

## crest: the padding rule

| trailing silence | reported crest dB | drift dB |
|---:|---:|---:|
| 0 s | 20.36 | +0.00 |
| 0.5 s | 20.5 | +0.14 |
| 1.0 s | 20.64 | +0.28 |
| 2.0 s | 20.9 | +0.54 |
