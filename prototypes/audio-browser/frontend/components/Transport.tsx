"use client";

/** Play, pause, step, scrub position, and volume for the shared player. */

import { usePlayer } from "@/components/PlayerProvider";
import { formatTime } from "@/lib/format";

export function TransportButtons({ compact = false }: { compact?: boolean }) {
  const player = usePlayer();
  const hasQueue = player.index !== null;

  return (
    <div className="buttons">
      <button
        type="button"
        className="btn"
        aria-label="previous track"
        data-testid="previous"
        disabled={!hasQueue}
        onClick={() => player.previous()}
      >
        ⏮
      </button>
      <button
        type="button"
        className="btn primary"
        aria-label={player.playing ? "pause" : "play"}
        data-testid="play-pause"
        onClick={() => player.toggle()}
      >
        {player.playing ? "⏸" : "▶"}
      </button>
      <button
        type="button"
        className="btn"
        aria-label="next track"
        data-testid="next"
        disabled={!hasQueue}
        onClick={() => player.next()}
      >
        ⏭
      </button>
      {compact ? null : (
        <span className="time mono" data-testid="time">
          {formatTime(player.time)} / {formatTime(player.duration)}
        </span>
      )}
    </div>
  );
}

export function Transport() {
  const player = usePlayer();
  return (
    <div className="transport">
      <TransportButtons />
      <div className="vol">
        volume
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={player.volume}
          aria-label="volume"
          onChange={(e) => player.setVolume(Number(e.target.value))}
        />
      </div>
    </div>
  );
}
