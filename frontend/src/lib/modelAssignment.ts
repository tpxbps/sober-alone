import type { ModelHealthItem } from '@/types/capabilities'
import type { AIModelOption, Character } from '@/types/game'

function shuffled<T>(items: T[], random: () => number): T[] {
  const result = [...items]
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1))
    const current = result[index]
    result[index] = result[swapIndex]
    result[swapIndex] = current
  }
  return result
}

export function assignModelsToAICharacters({
  characters,
  humanCharacterId,
  models,
  healthById,
  random = Math.random,
}: {
  characters: Character[]
  humanCharacterId: string
  models: AIModelOption[]
  healthById: Record<string, ModelHealthItem>
  random?: () => number
}): Record<string, string> {
  const aiCharacterIds = characters
    .filter((character) => character.character_id !== humanCharacterId)
    .map((character) => character.character_id)
  if (aiCharacterIds.length === 0 || models.length === 0) return {}

  const responsiveModels = models.filter(
    (model) => healthById[model.id]?.status === 'normal',
  )
  const unverifiedModels = models.filter((model) => {
    const status = healthById[model.id]?.status
    return status === undefined || status === 'unknown'
  })
  const slowModels = models.filter((model) => healthById[model.id]?.status === 'slow')
  const timedOutModels = models.filter((model) => healthById[model.id]?.status === 'timeout')
  const candidateModels =
    responsiveModels.length > 0
      ? responsiveModels
      : unverifiedModels.length > 0
        ? unverifiedModels
        : slowModels.length > 0
          ? slowModels
          : timedOutModels.length > 0
            ? timedOutModels
            : models
  const randomizedModels = shuffled(candidateModels, random)

  return Object.fromEntries(
    aiCharacterIds.map((characterId, index) => [
      characterId,
      randomizedModels[index % randomizedModels.length].id,
    ]),
  )
}
