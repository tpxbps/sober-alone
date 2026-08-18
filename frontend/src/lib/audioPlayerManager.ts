/**
 * audioPlayerManager - 全局单例音频播放管理器
 *
 * 支持两种播放模式：
 * 1. 静态音频：play(url) - 播放预生成/缓存的音频文件
 * 2. 流式音频：startStream / appendChunk / endStream - 实时流式播放
 *
 * 流式播放使用 MediaSource API 边收边播，
 * 流结束后自动生成 Blob URL 缓存到 blobCache 供重播使用。
 */

type StateChangeCallback = (isPlaying: boolean, progress: number, duration: number) => void;

type PlayMode = 'static' | 'streaming' | null;

class AudioPlayerManager {
  private mode: PlayMode = null;

  // ========== 静态播放 ==========
  private currentAudio: HTMLAudioElement | null = null;

  // ========== 流式播放 ==========
  private mediaSource: MediaSource | null = null;
  private sourceBuffer: SourceBuffer | null = null;
  private streamingAudio: HTMLAudioElement | null = null;
  private streamingChunks: Uint8Array[] = [];
  private appendQueue: Uint8Array[] = [];
  private isAppending = false;

  // ========== Blob 缓存 ==========
  private blobCache: Map<number, string> = new Map();

  // ========== 公共状态 ==========
  private stateListeners: Set<StateChangeCallback> = new Set();
  private rafId: number | null = null;

  // ========== 状态通知 ==========
  private notifyStateChange() {
    const { isPlaying, progress, duration } = this.getState();
    this.stateListeners.forEach(cb => cb(isPlaying, progress, duration));
  }

  private getState() {
    if (this.mode === 'streaming' && this.streamingAudio) {
      const a = this.streamingAudio;
      return {
        isPlaying: !a.paused,
        progress: a.currentTime,
        duration: isFinite(a.duration) ? a.duration : 0,
      };
    }
    const a = this.currentAudio;
    if (!a) return { isPlaying: false, progress: 0, duration: 0 };
    return {
      isPlaying: !a.paused,
      progress: a.currentTime,
      duration: isFinite(a.duration) ? a.duration : 0,
    };
  }

  private startProgressLoop() {
    if (this.rafId !== null) return;
    const tick = () => {
      const playing = this.getState().isPlaying;
      if (!playing) {
        this.rafId = null;
        return;
      }
      this.notifyStateChange();
      this.rafId = requestAnimationFrame(tick);
    };
    this.rafId = requestAnimationFrame(tick);
  }

  private stopProgressLoop() {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  onStateChange(callback: StateChangeCallback): () => void {
    this.stateListeners.add(callback);
    return () => this.stateListeners.delete(callback);
  }

  getIsPlaying(): boolean {
    return this.getState().isPlaying;
  }

  isAudioActive(): boolean {
    return this.currentAudio !== null || this.streamingAudio !== null;
  }

  getProgress(): { currentTime: number; duration: number } {
    return { currentTime: this.getState().progress, duration: this.getState().duration };
  }

  seekTo(time: number) {
    const audio = this.mode === 'streaming' ? this.streamingAudio : this.currentAudio;
    if (audio && isFinite(audio.duration)) {
      audio.currentTime = Math.max(0, Math.min(time, audio.duration));
      this.notifyStateChange();
    }
  }

  setPlaybackRate(rate: number) {
    const audio = this.mode === 'streaming' ? this.streamingAudio : this.currentAudio;
    if (audio) {
      audio.playbackRate = rate;
    }
  }

  getPlaybackRate(): number {
    const audio = this.mode === 'streaming' ? this.streamingAudio : this.currentAudio;
    return audio?.playbackRate ?? 1;
  }

  // ========== Blob 缓存 ==========

  getCachedUrl(recordId: number): string | null {
    return this.blobCache.get(recordId) || null;
  }

  setCachedUrl(recordId: number, url: string) {
    this.blobCache.set(recordId, url);
  }

  // ========== 静态音频播放 ==========

  async play(url: string): Promise<void> {
    this.stopStream();
    this.stopStatic();

    this.mode = 'static';
    const audio = new Audio(url);
    audio.volume = 1.0;
    audio.preload = 'auto';
    this.currentAudio = audio;
    this.notifyStateChange();

    audio.onended = () => {
      this.stopProgressLoop();
      this.currentAudio = null;
      this.notifyStateChange();
    };
    audio.onerror = () => {
      this.stopProgressLoop();
      console.error('[AudioPlayer] Error playing:', url);
      this.currentAudio = null;
      this.notifyStateChange();
    };
    audio.ontimeupdate = () => {
      this.notifyStateChange();
    };

    try {
      await audio.play();
      this.startProgressLoop();
    } catch (e) {
      console.error('[AudioPlayer] Error loading audio:', e);
      this.currentAudio = null;
      this.notifyStateChange();
    }
  }

  togglePause(): boolean {
    const audio = this.mode === 'streaming' ? this.streamingAudio : this.currentAudio;
    if (!audio) return false;
    if (audio.paused) {
      audio.play().catch(() => {});
      this.startProgressLoop();
      return true;
    } else {
      audio.pause();
      this.stopProgressLoop();
      return false;
    }
  }

  private stopStatic() {
    if (this.currentAudio) {
      const old = this.currentAudio;
      old.onended = null;
      old.onerror = null;
      old.ontimeupdate = null;
      old.pause();
      old.removeAttribute('src');
      old.load();
      this.currentAudio = null;
    }
  }

  // ========== 流式音频播放 (MediaSource) ==========

  async startStream(): Promise<void> {
    this.stopStream();
    this.stopStatic();
    this.stopProgressLoop();

    this.mode = 'streaming';
    this.streamingChunks = [];
    this.appendQueue = [];
    this.isAppending = false;

    // 检查 MediaSource 是否支持 MP3
    if (!MediaSource.isTypeSupported('audio/mpeg')) {
      throw new Error('Browser does not support MediaSource audio/mpeg');
    }

    this.mediaSource = new MediaSource();
    this.streamingAudio = new Audio();
    this.streamingAudio.src = URL.createObjectURL(this.mediaSource);
    this.streamingAudio.onended = () => {
      this.stopProgressLoop();
      this.streamingAudio = null;
      this.notifyStateChange();
    };
    this.streamingAudio.onerror = () => {
      this.stopProgressLoop();
      console.error('[AudioPlayer] Streaming audio error');
      this.streamingAudio = null;
      this.notifyStateChange();
    };

    // 等待 sourceopen
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('MediaSource timeout')), 5000);
      this.mediaSource!.addEventListener('sourceopen', () => {
        clearTimeout(timeout);
        this.sourceBuffer = this.mediaSource!.addSourceBuffer('audio/mpeg');
        this.sourceBuffer.mode = 'sequence';
        resolve();
      }, { once: true });
    });

    this.notifyStateChange();
  }

  async appendChunk(base64Audio: string): Promise<void> {
    const bytes = base64ToUint8Array(base64Audio);
    this.streamingChunks.push(bytes);

    if (!this.sourceBuffer) return;

    // 排队追加（必须串行，一次只能 appendBuffer 一个）
    this.appendQueue.push(bytes);
    this.processAppendQueue();

    // 第一个 chunk 到达时开始播放
    if (this.streamingAudio && this.streamingAudio.paused && this.streamingChunks.length === 1) {
      try {
        await this.streamingAudio.play();
        this.startProgressLoop();
      } catch {
        // autoplay 可能被阻止
      }
    }
  }

  private processAppendQueue() {
    if (this.isAppending || this.appendQueue.length === 0 || !this.sourceBuffer) return;

    this.isAppending = true;
    const chunk = this.appendQueue.shift()!;

    const doAppend = () => {
      try {
        this.sourceBuffer!.appendBuffer(chunk.buffer as ArrayBuffer);
      } catch {
        this.isAppending = false;
        return;
      }
    };

    if (this.sourceBuffer.updating) {
      const handler = () => {
        this.sourceBuffer!.removeEventListener('updateend', handler);
        doAppend();
      };
      this.sourceBuffer.addEventListener('updateend', handler);
    } else {
      doAppend();
    }

    const endHandler = () => {
      this.sourceBuffer!.removeEventListener('updateend', endHandler);
      this.isAppending = false;
      this.processAppendQueue(); // 处理队列中下一个
    };
    this.sourceBuffer.addEventListener('updateend', endHandler);
  }

  endStream(recordId: number): string | null {
    if (this.mediaSource && this.mediaSource.readyState === 'open') {
      try {
        this.mediaSource.endOfStream();
      } catch {
        // ignore
      }
    }

    // 缓存
    if (this.streamingChunks.length > 0) {
      const blob = new Blob(this.streamingChunks as BlobPart[], { type: 'audio/mpeg' });
      const blobUrl = URL.createObjectURL(blob);
      this.blobCache.set(recordId, blobUrl);
      return blobUrl;
    }
    return null;
  }

  private stopStream() {
    if (this.streamingAudio) {
      const old = this.streamingAudio;
      old.onended = null;
      old.onerror = null;
      old.pause();
      old.removeAttribute('src');
      old.load();
      this.streamingAudio = null;
    }
    if (this.mediaSource) {
      if (this.mediaSource.readyState === 'open') {
        try { this.mediaSource.endOfStream(); } catch { /* already closed */ }
      }
      this.mediaSource = null;
    }
    this.sourceBuffer = null;
    this.streamingChunks = [];
    this.appendQueue = [];
    this.isAppending = false;
  }

  // ========== 通用控制 ==========

  stop(): void {
    this.stopProgressLoop();
    this.stopStream();
    this.stopStatic();
    this.mode = null;
    this.notifyStateChange();
  }
}

/** base64 字符串转 Uint8Array */
function base64ToUint8Array(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export const audioPlayerManager = new AudioPlayerManager();
