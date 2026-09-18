import { expect, it } from 'vitest';
import type { ModelHealthItem, ModelHealthResponse } from '@/types/capabilities';
import { modelHealthMessage } from './modelHealthPresentation';

const sample = (status: ModelHealthItem['status']): ModelHealthItem => ({
  model: 'test', status, latency_ms: null, first_token_latency_ms: null,
  reaction_latency_ms: null, failed_dimensions: [], slow_dimensions: [],
  message: '', checked_at: '',
});
const result = (models: ModelHealthItem[]): ModelHealthResponse => ({ models, cached: false, max_age_seconds: 30 });

it('does not announce updated success for failed or empty samples', () => {
  expect(modelHealthMessage(result([sample('unknown')]), true)).toContain('未取得完整结果');
  expect(modelHealthMessage(result([]), true)).toBe('暂无可测速的模型。');
  expect(modelHealthMessage(result([sample('normal')]), true)).toBe('测速已更新');
  expect(modelHealthMessage(result([sample('normal'), sample('timeout')]), true)).toContain('部分模型');
});

it('explains service credentials and distinguishes the short retry cooldown', () => {
  expect(modelHealthMessage({ ...result([sample('unknown')]), service_error: 'probe_auth' })).toContain('这不代表各模型不可用');
  expect(modelHealthMessage({ ...result([sample('normal')]), cached: true, retry_after_seconds: 7 }, true)).toContain('7 秒后');
});
