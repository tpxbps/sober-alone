import type { GameDataSections } from '@/types/editor';

/** character_data is canonical; name-keyed maps and scene aliases are transport compatibility only. */
export function submissionData(draft: GameDataSections): GameDataSections {
  const data = structuredClone(draft);
  data.character_data = data.character_data.map(role => ({ ...role,
    character_script: role.character_script ?? data.character_scripts[role.name] ?? '',
  }));
  data.character_scripts = Object.fromEntries(data.character_data.map(role => [role.name, role.character_script || '']));
  for (const scene of data.game_flow) {
    if (scene.type === 'initial') scene.system_notice = data.opening;
    if (scene.type === 'review') scene.system_notice = data.truth_reveal;
  }
  return data;
}
