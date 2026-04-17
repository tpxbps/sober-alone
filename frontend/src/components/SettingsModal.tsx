import { motion } from 'framer-motion';
import { Volume2, VolumeX, Mic, MicOff } from 'lucide-react';
import { useSettingsStore } from '@/stores/settingsStore';

interface SettingsModalProps {
  onClose: () => void;
}

export function SettingsModal({ onClose }: SettingsModalProps) {
  const {
    bgmEnabled,
    bgmVolume,
    ttsEnabled,
    setBgmEnabled,
    setBgmVolume,
    setTtsEnabled,
  } = useSettingsStore();

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 20 }}
        className="bg-card rounded-xl p-6 min-w-[320px] shadow-2xl border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold mb-5">设置</h3>

        {/* BGM Toggle */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {bgmEnabled ? (
              <Volume2 className="w-5 h-5 text-primary" />
            ) : (
              <VolumeX className="w-5 h-5 text-muted-foreground" />
            )}
            <span className="text-sm font-medium">背景音乐</span>
          </div>
          <button
            onClick={() => setBgmEnabled(!bgmEnabled)}
            className={`w-11 h-6 rounded-full transition-colors relative ${
              bgmEnabled ? "bg-primary" : "bg-secondary"
            }`}
          >
            <div
              className={`w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${
                bgmEnabled ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        {/* Volume Slider */}
        {bgmEnabled && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground">音量</span>
              <span className="text-xs text-muted-foreground">
                {Math.round(bgmVolume * 100)}%
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              value={Math.round(bgmVolume * 100)}
              onChange={(e) => setBgmVolume(Number(e.target.value) / 100)}
              className="w-full h-1.5 rounded-full appearance-none bg-secondary cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4
                         [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full
                         [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow"
            />
          </motion.div>
        )}

        {/* Divider */}
        <div className="border-t border-border/50 my-4" />

        {/* TTS Toggle */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {ttsEnabled ? (
              <Mic className="w-5 h-5 text-primary" />
            ) : (
              <MicOff className="w-5 h-5 text-muted-foreground" />
            )}
            <div className="flex flex-col">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-medium">语音播报</span>
                <span className="inline-block px-1.5 py-0 rounded text-[10px] font-medium bg-primary/20 text-primary leading-4">
                  Beta
                </span>
              </div>
              <span className="text-xs text-muted-foreground">
                AI 角色发言自动转为语音播放
              </span>
            </div>
          </div>
          <button
            onClick={() => setTtsEnabled(!ttsEnabled)}
            className={`w-11 h-6 rounded-full transition-colors relative ${
              ttsEnabled ? "bg-primary" : "bg-secondary"
            }`}
          >
            <div
              className={`w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${
                ttsEnabled ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        <button
          onClick={onClose}
          className="w-full mt-4 px-4 py-2.5 rounded-lg bg-secondary hover:bg-secondary/80
                   text-sm font-medium transition-colors"
        >
          关闭
        </button>
      </motion.div>
    </motion.div>
  );
}
