import type { PublicClue } from './game';

export interface ClueMedia {
  image_url: string;
  thumbnail_url: string;
  alt: string;
  focus: [number, number];
  mobile_focus?: [number, number];
  source_hash?: string;
  status: 'ready' | 'needs_review';
}
export interface ClueShot {
  id: string;
  duration_ms: number;
  clue_ids: string[];
  title: string;
  caption: string;
  emphasis: string;
  motion: 'push' | 'pan' | 'split' | 'reveal' | 'timeline' | 'chain';
  labels: string[];
  composition?: 'pan' | 'detail' | 'pair' | 'occlusion' | 'light';
}
export interface CluePresentation {
  version: 1 | 2;
  revision: string;
  template: 'cinematic' | 'dossier';
  visual_preset?: 'warm-noir' | 'cold-occlusion' | 'candle-silk' | 'afternoon-paper' | 'orbital-steel';
  title: string;
  background?: ClueMedia;
  shots: ClueShot[];
  source_hash?: string;
  status: 'ready' | 'needs_review';
}
export interface CluePresentationState {
  presentation_id: string;
  round: number;
  status: 'pending' | 'acknowledged';
  presentation: CluePresentation | null;
  clues: PublicClue[];
  reference_clues?: PublicClue[];
}
