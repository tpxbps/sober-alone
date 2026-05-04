import { motion } from "framer-motion";
import { Mic, MicOff } from "lucide-react";
import type { PlayerState, Character, GameStage } from "@/types/game";

interface CharacterPanelProps {
  stage: GameStage;
  characters: Character[];
  playerStates: PlayerState[];
  currentSpeakerId: string | null;
  humanCharacterId: string | null;
  onCharacterClick?: (characterId: string) => void;
  side: "left" | "right";
}

export function CharacterPanel({
  stage,
  characters,
  playerStates,
  currentSpeakerId,
  humanCharacterId,
  onCharacterClick,
  side,
}: CharacterPanelProps) {
  // Split characters into two groups based on side
  const midPoint = Math.ceil(characters.length / 2);
  const displayCharacters =
    side === "left"
      ? characters.slice(0, midPoint)
      : characters.slice(midPoint);

  // Get player state for a character
  const getPlayerState = (characterId: string): PlayerState | undefined => {
    return playerStates.find((ps) => ps.character_id === characterId);
  };

  // Check if character is currently speaking
  const isSpeaking = (characterId: string): boolean => {
    return currentSpeakerId === characterId;
  };

  // Check if character is human
  const isHuman = (characterId: string): boolean => {
    return humanCharacterId === characterId;
  };

  return (
    <div
      className={`flex flex-col gap-3 ${
        side === "right" ? "items-end" : "items-start"
      }`}
    >
      {displayCharacters.map((character, index) => {
        const playerState = getPlayerState(character.character_id);
        const speaking = isSpeaking(character.character_id);
        const human = isHuman(character.character_id);

        return (
          <motion.div
            key={character.character_id}
            initial={{ opacity: 0, x: side === "left" ? -20 : 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.1 }}
            onClick={() => onCharacterClick?.(character.character_id)}
            className="relative group cursor-pointer"
          >
            {/* Character Card - Fixed width for all items */}
            <div
              className={`relative flex items-center gap-3 p-3 rounded-xl transition-all duration-300 w-56
                ${
                  speaking
                    ? "bg-primary/20 border border-primary/50 breathing"
                    : "bg-card/50 border border-border/30 hover:border-border/50 hover:bg-card/70"
                }
                ${side === "right" ? "flex-row-reverse" : "flex-row"}`}
            >
              {/* Avatar */}
              <div
                className={`relative w-11 h-11 rounded-full overflow-hidden shrink-0
                  ${
                    speaking
                      ? "ring-2 ring-primary ring-offset-2 ring-offset-background"
                      : ""
                  }`}
              >
                {character.avatar_url ? (
                  <img
                    src={character.avatar_url}
                    alt={character.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div
                    className="w-full h-full bg-gradient-to-br from-primary/30 to-accent/30
                                flex items-center justify-center text-lg font-bold"
                  >
                    {character.name[0]}
                  </div>
                )}

                {/* Speaking indicator */}
                {speaking && (
                  <div className="absolute inset-0 bg-primary/20 flex items-center justify-center">
                    <Mic className="w-5 h-5 text-primary animate-pulse" />
                  </div>
                )}
              </div>

              {/* Info */}
              <div
                className={`flex-1 min-w-0 ${
                  side === "right" ? "text-right" : "text-left"
                }`}
              >
                <div
                  className={`flex items-center gap-1 ${
                    side === "right" ? "justify-end" : "justify-start"
                  }`}
                >
                  <span
                    className={`font-medium truncate ${
                      speaking ? "text-primary" : ""
                    }`}
                  >
                    {character.name}
                  </span>
                  {human && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded-full bg-accent text-accent-foreground font-medium shrink-0">
                      你
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground truncate">
                  {character.occupation}
                </p>
              </div>

              {/* Status Icons */}
              <div className="flex items-center gap-1.5 shrink-0">
                {/* Has spoken indicator */}
                {playerState?.has_spoken_this_round ? (
                  <MicOff className="w-4 h-4 text-muted-foreground" />
                ) : (
                  <Mic className="w-4 h-4 text-primary/50" />
                )}
              </div>
            </div>

            {/* Hover tooltip */}
            <div
              className={`absolute ${
                side === "left" ? "left-full" : "right-full"
              }
                top-0 bottom-0 z-50
                flex items-center opacity-0 group-hover:opacity-100
                transition-opacity duration-200
                pointer-events-none group-hover:pointer-events-auto
                ${side === "left" ? "pl-2" : "pr-2"}`}
            >
              <div className="p-4 rounded-xl bg-popover border border-border shadow-lg text-sm w-80">
                <div className="flex items-center gap-2 mb-2">
                  <div
                    className="w-8 h-8 rounded-full overflow-hidden bg-gradient-to-br from-primary/30 to-accent/30
                                flex items-center justify-center text-sm font-bold shrink-0"
                  >
                    {character.avatar_url ? (
                      <img
                        src={character.avatar_url}
                        alt={character.name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      character.name[0]
                    )}
                  </div>
                  <div>
                    <p className="font-medium">{character.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {character.occupation}
                    </p>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed max-h-32 overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                  {character.profile ||
                    character.character_script_summary ||
                    "暂无角色简介"}
                </p>
                {playerState && (
                  <div className="mt-3 pt-2 border-t border-border/50 text-xs space-y-1">
                    <div className="flex justify-between text-muted-foreground">
                      <span>本阶段发言</span>
                      <span className="text-foreground">
                        {playerState.speeches_this_round ?? 0} 次
                      </span>
                    </div>
                    {stage === "free_discussion" && (
                      <div className="flex justify-between text-muted-foreground">
                        <span>剩余发言机会</span>
                        <span className="text-foreground">
                          {playerState.remaining_speech_count ?? "-"} 次
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
