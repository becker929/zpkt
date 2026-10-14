// What the four references measure, and HW002 against them (ears/mlab, 1 October 2026; docs/hw002/references.md,
// ~/_agent_scratch/mixclimb/targets.json). Each is the 30 s peak window of the track. Band levels are relative to
// the window's own total power (the 29 bands sum to 0 dB), so loudness cancels and only the shape is compared.
// References: BSLS, Hedon, KSMS, Patriotic.

export const THIRDS = [   // [centre Hz, refs min, refs mean, refs max, HW002 (the set, measured)]
  [25.1, -35.1, -33.343, -29.89, -41.28],
  [31.6, -27.56, -25.477, -22.61, -34.36],
  [39.8, -20.51, -15.888, -11.86, -23.19],
  [50.1, -12.14, -8.045, -5.45, -11.29],
  [63.1, -8.25, -6.928, -5.49, -5.43],
  [79.4, -12.14, -8.595, -6.08, -5.41],
  [100.0, -13.58, -10.602, -6.05, -9.66],
  [125.9, -15.6, -14.445, -11.45, -12.89],
  [158.5, -23.29, -17.637, -13.4, -14.52],
  [199.5, -26.53, -18.395, -12.91, -15.33],
  [251.2, -21.65, -19.018, -15.13, -18.79],
  [316.2, -25.86, -21.41, -16.31, -21.83],
  [398.1, -28.49, -21.36, -16.23, -22.43],
  [501.2, -26.19, -20.75, -17.39, -22.63],
  [631.0, -21.93, -19.215, -14.94, -23.93],
  [794.3, -21.2, -17.745, -14.21, -21.99],
  [1000.0, -19.05, -17.723, -16.07, -24.17],
  [1258.9, -19.4, -17.992, -14.83, -24.31],
  [1584.9, -20.91, -18.47, -15.2, -24.57],
  [1995.3, -20.7, -18.892, -17.64, -26.47],
  [2511.9, -19.81, -18.488, -16.98, -26.63],
  [3162.3, -19.97, -18.745, -17.51, -24.71],
  [3981.1, -22.29, -19.892, -18.67, -22.61],
  [5011.9, -22.57, -20.335, -18.75, -19.86],
  [6309.6, -23.81, -20.913, -18.92, -17.87],
  [7943.3, -26.1, -22.265, -19.81, -18.55],
  [10000.0, -29.35, -24.725, -22.52, -19.77],
  [12589.3, -34.78, -28.078, -25.05, -24.32],
  [15848.9, -40.66, -32.513, -26.84, -27.03],
];

/**
 * The phone's RTA (two 32768-point analysers, the bins of each band summed) against mlab's (a Welch PSD) on the same
 * audio: the lab's 24 bars at the set's values, two whole passes, both relative. Added to the phone's band levels so
 * that at the set they sit on HW002's own measurement. The low bands read high on the phone (the FFT's main lobe
 * smears the 50-80 Hz kick into its neighbours); the rest shift by the normalisation. Measured 2026-10-14.
 */
export const CAL = [-2.6, -0.63, -1.68, -2.22, 0.29, 0.23, -0.01, -0.02, 0.28, 0.17, -0.19, 0.35, 0.07, 0.47, 0.61, 0.38,
  0.52, 0.29, 0.39, 0.7, 0.6, 0.58, 0.54, 0.61, 0.62, 0.62, 0.63, 0.65, 0.73];

/** The three tonal gaps the mix has to close, and the bands in each (the gap is their mean against the refs' mean). */
export const ZONES = [
  { id: 'sub', label: 'Deep sub', lo: 22.4, hi: 44.7, bands: [25.1, 31.6, 39.8], say: 'more sub under 40 Hz' },
  { id: 'mids', label: 'Mids', lo: 891, hi: 3548, bands: [1000.0, 1258.9, 1584.9, 1995.3, 2511.9, 3162.3], say: 'more 1-3 kHz bite' },
  { id: 'air', label: 'Air', lo: 7079, hi: 14125, bands: [7943.3, 10000.0, 12589.3], say: 'less fizz near 10 kHz' },
];

export const REF = {
  // below 120 Hz
  corrLow: { min: 0.987, max: 1.0, set: 0.876 },
  sideMidLow: { min: -45.05, max: -21.88, set: -11.8 },
  // the peak's density: median crest of 400 ms blocks
  crest: { min: 4.41, max: 6.62, set: 8.72 },
  // loudness, LUFS integrated; true peak dBTP
  refsLufs: { min: -7.2, max: -4.3 },
  master: { min: -14, max: -11, tp: -1.5 },
  setLufs: -14.1,
  centroid: { min: 2691, max: 3844, set: 5196 },
};

/** Each reference's integrated loudness and PLR, for the loudness meter's legend. */
export const TRACKS = [
  { name: 'BSLS', lufs: -4.3, tp: -0.0, plr: 4.3 },
  { name: 'Hedon', lufs: -5.2, tp: -1.0, plr: 4.3 },
  { name: 'KSMS', lufs: -7.2, tp: -0.4, plr: 6.9 },
  { name: 'Patriotic', lufs: -6.8, tp: -0.2, plr: 6.6 },
];
