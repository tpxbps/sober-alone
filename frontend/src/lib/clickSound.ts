/**
 * Global click sound effect for game buttons.
 * Attaches a single delegated listener to the document.
 * Only plays for <button> clicks that are not disabled.
 */

const CLICK_SOUND_SRC = '/audio/click.wav';
let audio: HTMLAudioElement | null = null;
let attached = false;

function getAudio(): HTMLAudioElement {
  if (!audio) {
    audio = new Audio(CLICK_SOUND_SRC);
    audio.volume = 0.25;
    audio.preload = 'auto';
  }
  return audio;
}

function handleClick(e: MouseEvent) {
  // Find closest <button> ancestor of the click target
  const target = (e.target as HTMLElement).closest('button');
  if (!target) return;
  // Skip disabled buttons
  if (target.disabled) return;

  const a = getAudio();
  a.currentTime = 0;
  a.play().catch(() => {});
}

/**
 * Initialize global click sound listener (call once at app startup).
 */
export function initClickSound() {
  if (attached) return;
  document.addEventListener('click', handleClick, true);
  attached = true;
}

/**
 * Remove global click sound listener (for cleanup / testing).
 */
export function destroyClickSound() {
  if (!attached) return;
  document.removeEventListener('click', handleClick, true);
  attached = false;
}
