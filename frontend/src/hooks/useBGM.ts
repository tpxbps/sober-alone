import { useRef, useCallback, useEffect } from 'react';
import { useSettingsStore } from '@/stores/settingsStore';
import type { GameStage } from '@/types/game';

// Stage → BGM file mapping (string for single track, string[] for random pick)
const STAGE_BGM: Partial<Record<GameStage, string | string[]>> = {
  intro: '/audio/intro.mp3',
  clue_analysis: ['/audio/clue1.mp3', '/audio/clue2.mp3', '/audio/clue3.mp3'],
  free_discussion: ['/audio/clue1.mp3', '/audio/clue2.mp3', '/audio/clue3.mp3'],
  summary: ['/audio/clue1.mp3', '/audio/clue2.mp3', '/audio/clue3.mp3'],
  vote: '/audio/vote.mp3',
  review: '/audio/vote.mp3',
  completed: '/audio/vote.mp3',
};

const LOBBY_TRACKS = [
  '/audio/lobby1.mp3',
  '/audio/lobby2.mp3',
  '/audio/lobby3.mp3',
];

const FADE_DURATION = 1.2; // seconds
const FADE_STEP_MS = 50;

// ============ Global singleton audio manager ============
// Ensures only ONE audio track plays at a time across all hook instances.
let _globalAudio: HTMLAudioElement | null = null;
let _globalCurrentSrc: string | null = null;
let _globalDesiredSrc: string | null = null;
let _globalUnlocked = false;

function fadeAudio(audio: HTMLAudioElement, target: number, duration = FADE_DURATION): Promise<void> {
  return new Promise((resolve) => {
    if (audio.paused) {
      audio.volume = target;
      resolve();
      return;
    }
    const steps = Math.round(duration * 1000 / FADE_STEP_MS);
    const start = audio.volume;
    if (Math.abs(start - target) < 0.01) {
      audio.volume = target;
      resolve();
      return;
    }
    const delta = (target - start) / steps;
    let i = 0;
    const timer = setInterval(() => {
      i++;
      if (i >= steps) {
        clearInterval(timer);
        audio.volume = target;
        resolve();
      } else {
        audio.volume = Math.max(0, Math.min(1, start + delta * i));
      }
    }, FADE_STEP_MS);
  });
}

function _stopGlobalAudio() {
  if (_globalAudio) {
    _globalAudio.pause();
    _globalAudio.src = '';
    _globalAudio = null;
    _globalCurrentSrc = null;
  }
}

function _startGlobalAudio(src: string, volume: number) {
  // Same track already playing? Skip.
  if (_globalAudio && !_globalAudio.paused && _globalCurrentSrc === src) {
    return;
  }

  const audio = new Audio();
  audio.preload = 'auto';
  audio.loop = true;
  audio.volume = 0;
  // Suppress console errors for missing audio files
  audio.onerror = () => {};
  audio.src = src;

  const oldAudio = _globalAudio;
  if (oldAudio) {
    fadeAudio(oldAudio, 0, 0.6).then(() => {
      oldAudio.pause();
      oldAudio.src = '';
    });
  }

  _globalAudio = audio;
  _globalCurrentSrc = src;

  audio.play().then(() => {
    fadeAudio(audio, volume);
  }).catch(() => {
    // Autoplay blocked — will retry once unlocked
  });
}

export function useBGM() {
  // Use refs for settings so callbacks stay stable
  const bgmEnabledRef = useRef(useSettingsStore.getState().bgmEnabled);
  const bgmVolumeRef = useRef(useSettingsStore.getState().bgmVolume);

  // Subscribe to settings changes — update refs only
  useEffect(() => {
    return useSettingsStore.subscribe((state) => {
      const prevEnabled = bgmEnabledRef.current;
      const prevVolume = bgmVolumeRef.current;

      bgmEnabledRef.current = state.bgmEnabled;
      bgmVolumeRef.current = state.bgmVolume;

      // Volume changed → apply instantly to playing audio
      if (state.bgmVolume !== prevVolume && _globalAudio && !_globalAudio.paused) {
        _globalAudio.volume = state.bgmVolume;
      }

      // Enabled toggled → pause or resume
      if (state.bgmEnabled !== prevEnabled) {
        if (!state.bgmEnabled) {
          if (_globalAudio) _globalAudio.pause();
        } else if (_globalDesiredSrc && _globalUnlocked) {
          _startGlobalAudio(_globalDesiredSrc, bgmVolumeRef.current);
        }
      }
    });
  }, []); 

  // --- Public: play a specific track ---
  const playTrack = useCallback(
    (src: string) => {
      _globalDesiredSrc = src;

      if (!bgmEnabledRef.current) {
        _stopGlobalAudio();
        return;
      }

      if (!_globalUnlocked) {
        // Preload only
        return;
      }

      _startGlobalAudio(src, bgmVolumeRef.current);
    },
    [] // stable — reads enabled/volume from refs
  );

  // --- Public: stop playback ---
  const stop = useCallback(() => {
    _globalDesiredSrc = null;
    if (_globalAudio) {
      fadeAudio(_globalAudio, 0, 0.5).then(() => {
        _stopGlobalAudio();
      });
    }
  }, []);

  // --- Public: play random lobby track ---
  const playLobby = useCallback(() => {
    const track = LOBBY_TRACKS[Math.floor(Math.random() * LOBBY_TRACKS.length)];
    playTrack(track);
  }, [playTrack]);

  // --- Public: play stage BGM ---
  const playStage = useCallback(
    (stage: GameStage) => {
      const tracks = STAGE_BGM[stage];
      if (!tracks) return;
      const track = Array.isArray(tracks)
        ? tracks[Math.floor(Math.random() * tracks.length)]
        : tracks;
      playTrack(track);
    },
    [playTrack]
  );

  // --- Unlock autoplay on first user gesture ---
  useEffect(() => {
    const unlock = () => {
      if (_globalUnlocked) return;
      _globalUnlocked = true;
      if (_globalDesiredSrc && bgmEnabledRef.current) {
        _startGlobalAudio(_globalDesiredSrc, bgmVolumeRef.current);
      }
      window.removeEventListener('click', unlock);
      window.removeEventListener('keydown', unlock);
      window.removeEventListener('touchstart', unlock);
    };
    window.addEventListener('click', unlock);
    window.addEventListener('keydown', unlock);
    window.addEventListener('touchstart', unlock);
    return () => {
      window.removeEventListener('click', unlock);
      window.removeEventListener('keydown', unlock);
      window.removeEventListener('touchstart', unlock);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return { playLobby, playStage, stop };
}
