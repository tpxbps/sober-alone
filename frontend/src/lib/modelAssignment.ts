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
  previous = {},
  random = Math.random,
}: {
  characters: Character[]
  humanCharacterId: string
  models: AIModelOption[]
  healthById: Record<string, ModelHealthItem>
  previous?: Record<string, string>
  random?: () => number
}): Record<string, string> {
  // Frontier models are an explicit player choice, including when every
  // inexpensive model is slow or health information is not available yet.
  const aiCharacterIds = characters
    .filter((character) => character.character_id !== humanCharacterId)
    .map((character) => character.character_id)
  const retained = Object.fromEntries(aiCharacterIds
    .filter(id => models.some(model => model.id === previous[id]))
    .map(id => [id, previous[id]]))
  const unassignedIds = aiCharacterIds.filter(id => !retained[id])
  models = models.filter((model) => model.tier !== 'frontier')
  // Late health samples are advisory. Only a missing or removed model needs
  // assignment; never reshuffle choices already displayed to the player.
  if (unassignedIds.length === 0 || models.length === 0) return retained

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

  return { ...retained, ...Object.fromEntries(
    unassignedIds.map((characterId, index) => [
      characterId,
      randomizedModels[index % randomizedModels.length].id,
    ]),
  ) }
}
