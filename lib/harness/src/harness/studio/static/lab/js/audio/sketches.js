// How the phone sounds HW002's kick and mix params on the set's own stems.
//
// The stems already carry the set's sound, so each sketch plays only the change from the set's value: +6 dB on the
// 30 Hz shelf is a 30 Hz shelf of +6 dB on the kick group's stem, at the set's value nothing at all. Where the set's
// processing cannot be taken back out of a stem (less drive than the set, a layer inside the kick group), the sketch
// does what it can and says so in a comment. The kick group stem holds the kick and the rumble; the surfaces' own
// instruments (the kick synth, the collage) add their own sketches to the same keys.

const DECAP = ['tanh', 'tube', 'tube', 'hard', 'fold'];          // A, E, N, T, P: what each style leans towards

export function installSketches(engine) {
  const st = { drive: {}, colour: { freq: null, gain: 0 } };
  const on = (key, fn) => engine.sketch(key, fn);
  const bus = (name) => engine.bus(name);

  // ---- the kick group stem ------------------------------------------------------------------------------------
  on('kick.sub30', (d) => bus('kick').bandGain('sub30', d, 'lowshelf', 30));
  on('kick.sub35', (d) => bus('kick').bandGain('sub35', d, 'lowshelf', 35));
  on('kick.body', (d) => bus('kick').bandGain('body', d, 'peaking', 62.5, 0.82));
  on('kick.push', (d) => bus('kick').bandGain('push', d, 'peaking', 330, 1.0));
  on('kick.air', (d) => bus('kick').bandGain('air', d, 'highshelf', 5000));

  // Colour: the set boosts 484 Hz. Moving the frequency takes that boost out and puts it where the knob is.
  const colour = () => {
    const k = bus('kick'), c = st.colour;
    if (c.freq == null || c.setFreq == null) return;
    const moved = Math.abs(Math.log(c.freq / c.setFreq)) > 0.02;
    k.bandGain('colourUndo', moved ? -c.setGain : 0, 'peaking', c.setFreq, 1.2);
    k.bandGain('colour', moved ? c.setGain + c.gain : c.gain, 'peaking', c.freq, 1.2);
    k.bandFreq('colour', c.freq);
  };
  on('kick.colourFreq', (_d, i) => { st.colour.freq = i.real; st.colour.setFreq = i.set; colour(); });
  on('kick.colour', (d, i) => { st.colour.gain = d; st.colour.setGain = i.set; colour(); });

  // Distortion: COLDFIRE on the kick bus and the Decapitator on the rumble, one shaper on the kick stem. Less drive
  // than the set cannot be heard (it is in the stem); more is.
  const drive = () => {
    const k = bus('kick'), d = st.drive;
    const amount = Math.max(0, d.coldfire ?? 0) + Math.max(0, d.decap ?? 0) * 0.7 + (d.punish ? 0.45 : 0) + (d.roar ? 0.25 : 0);
    k.set('drive', Math.min(1, amount));
    k.set('driveType', d.roar && !(d.decap > 0) ? 'tube' : DECAP[d.style ?? 0]);
    k.set('driveMix', amount > 0.001 ? (d.mix ?? 1) : 0);
    k.bandGain('tone', (d.tone ?? 0) * 12, 'highshelf', 2500);
    k.bandGain('roarSub', d.roar ? -2.5 : 0, 'lowshelf', 60);       // Roar on: the sub's share drops (0.90 to 0.77)
  };
  on('kick.drive', (_d, i) => { st.drive.coldfire = i.dnorm; drive(); });
  on('rumble.drive', (_d, i) => { st.drive.decap = i.dnorm; drive(); });
  on('rumble.style', (_d, i) => { st.drive.style = i.real; drive(); });
  on('rumble.tone', (_d, i) => { st.drive.tone = i.dnorm; drive(); });
  on('rumble.punish', (_d, i) => { st.drive.punish = i.real > 0.5; drive(); });
  on('rumble.mix', (_d, i) => { st.drive.mix = i.norm; drive(); });
  on('kick.roar', (_d, i) => { st.drive.roar = i.real > 0.5; drive(); });

  // The drum rack's layers live inside the kick group stem: a level change moves the stem, weighted by how much of
  // it the layer is. The transient shaper is sketched as bands where its attack and sustain act.
  on('kick.l052', (d) => bus('kick').set('trim', d * 0.7));
  on('kick.l060', (d) => bus('kick').bandGain('l060', d * 0.3, 'peaking', 90, 0.7));
  on('kick.offbeat', (d) => bus('kick').bandGain('offbeat', d * 0.2, 'peaking', 180, 0.8));
  on('kick.attack', (_d, i) => bus('kick').bandGain('click', i.dnorm * 14, 'peaking', 3800, 0.9));
  on('kick.pump', (_d, i) => bus('kick').bandGain('pump', i.dnorm * 4, 'peaking', 110, 0.6));
  on('kick.sustain', (_d, i) => bus('kick').bandGain('tail', i.dnorm * 8, 'lowshelf', 140));
  on('kick.verb', (_d, i) => bus('kick').set('sendA', Math.max(0, i.dnorm) * 0.9));

  // The kick group's compressor: idle at the set (threshold over the bus). Lower the threshold and it bites.
  on('kick.thresh', (d) => bus('kick').set('compThreshold', Math.min(0, d)));
  on('kick.ratio', (_d, i) => bus('kick').set('compRatio', Math.max(1, i.real)));
  on('kick.cattack', (_d, i) => bus('kick').set('compAttack', Math.max(0.01, i.real)));
  on('kick.release', (_d, i) => bus('kick').set('compRelease', Math.max(1, i.real)));
  on('kick.cmix', (_d, i) => bus('kick').set('compMix', i.norm));

  // The rumble, inside the kick group stem.
  on('rumble.sub', (d) => bus('kick').bandGain('rsub', d * 0.8, 'lowshelf', 31));
  on('rumble.air', (d) => bus('kick').bandGain('rair', d * 0.5, 'highshelf', 5000));
  on('rumble.level', (d) => bus('kick').bandGain('rlevel', d * 0.8, 'lowshelf', 100));
  on('rumble.mono', (_d, i) => bus('kick').set('bassMono', i.real > 0.5));
  on('rumble.width', (_d, i) => bus('kick').set('width', i.real / Math.max(1, i.set)));
  on('rumble.pitch', () => {});                                       // a stem cannot be re-pitched in part

  // ---- the mix ----------------------------------------------------------------------------------------------------
  on('mix.kick', (d) => bus('kick').set('gain', d));
  on('mix.perc', (d) => bus('perc').set('gain', d));
  on('mix.sfx', (d) => bus('sfx').set('gain', d));
  on('mix.layerB', (d) => bus('perc').bandGain('layerB', d * 0.35, 'highshelf', 7000));

  const mono = { on: false, freq: 120 };
  const applyMono = () => {
    for (const name of ['kick', 'perc', 'sfx']) {
      const b = bus(name);
      if (name !== 'kick' || mono.on) b.set('bassMono', mono.on);   // the rumble's own toggle also drives the kick bus
      b.set('bassMonoFreq', mono.freq);
    }
  };
  on('mix.bassMono', (_d, i) => { mono.on = i.real > 0.5; applyMono(); });
  on('mix.monoFreq', (_d, i) => { mono.freq = i.real; applyMono(); });

  // Space: Supermassive on perc 2 is a delay-reverb. More mix than the set sends the perc stem to both returns.
  on('mix.spaceMix', (_d, i) => { const m = Math.max(0, i.dnorm); bus('perc').set('sendA', m * 1.4); bus('perc').set('sendB', m * 0.9); });
  on('mix.spaceFeedback', (_d, i) => engine.setMaster('delayFeedback', Math.min(0.92, i.norm * 0.9)));
  on('mix.spaceDelay', (_d, i) => engine.setMaster('delayTime', 0.25 + i.norm * 1.75));
  on('mix.spaceDensity', (_d, i) => engine.setMaster('reverbSize', 0.8 + i.norm * 4.5));
  on('mix.spaceHighCut', (_d, i) => engine.setMaster('reverbDamp', 1 - i.norm));

  on('mix.hatsBell', (d) => bus('perc').bandGain('bell1k', d, 'peaking', 1000, 1));
  on('mix.hatsAir', (d) => bus('perc').bandGain('air', d, 'highshelf', 5000));
  const percDrive = { a: 0, b: 0 };
  const applyPerc = () => {
    const amount = Math.max(0, percDrive.a) + Math.max(0, percDrive.b) * 0.6;
    bus('perc').set('drive', Math.min(1, amount));
    bus('perc').set('driveMix', amount > 0.001 ? 1 : 0);
  };
  on('mix.hatsDrive', (_d, i) => { percDrive.a = i.dnorm; applyPerc(); });
  on('mix.perc1Drive', (_d, i) => { percDrive.b = i.dnorm; applyPerc(); });

  // The Main's glue rack is off in the set: turning it on makes the master's glue act.
  const glue = { on: false, thr: 0, ratio: 4 };
  const applyGlue = () => {
    engine.setMaster('glueThreshold', glue.on ? glue.thr : 0);
    engine.setMaster('glueRatio', glue.on ? glue.ratio : 1);
  };
  on('mix.mainRack', (_d, i) => { glue.on = i.real > 0.5; applyGlue(); });
  on('mix.glueThresh', (_d, i) => { glue.thr = i.real; applyGlue(); });
  on('mix.glueRatio', (_d, i) => { glue.ratio = [2, 4, 10][i.real] ?? 4; applyGlue(); });

  on('mix.sfxVerb', (_d, i) => bus('sfx').set('sendA', Math.max(0, i.dnorm) * 1.2));
  on('mix.sfxDecay', (_d, i) => engine.setMaster('reverbSize', i.real));
  on('mix.sfxThresh', (d) => { bus('sfx').set('compThreshold', Math.min(0, d)); bus('sfx').set('compRatio', 3); bus('sfx').set('compMix', d < 0 ? 1 : 0); });
  on('mix.sfxLowCut', (_d, i) => bus('sfx').set('lowCut', i.real > i.set * 1.02 ? i.real : 10));
}
