import type { QualityReport } from '@/types/editor';

/** Older checkpoints/API responses use {} for a check that has not run. */
export function normalizeQualityReport(value: QualityReport | null | undefined): QualityReport | null {
  if (!value || Object.keys(value).length === 0) return null;
  if (!Array.isArray(value.findings)) {
    return { ...value, status: 'incomplete', findings: [], error: '已保存的质检报告不完整，仍可继续创作。' };
  }
  return value;
}
