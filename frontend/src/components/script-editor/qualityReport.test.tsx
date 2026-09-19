import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { QualityReport } from '@/types/editor';
import { normalizeQualityReport } from './qualityReport';
import { QualityReviewStage } from './QualityReviewStage';

describe('quality report compatibility', () => {
  it.each([undefined, null, {}])('treats %s as a check that has not run', value => {
    expect(normalizeQualityReport(value as QualityReport | null | undefined)).toBeNull();
  });

  it('preserves a completed report with zero findings', () => {
    const report: QualityReport = { report_id: 'r1', status: 'passed', findings: [], content_fingerprint: 'fp' };
    expect(normalizeQualityReport(report)).toBe(report);
  });

  it('does not present a partial saved report as a successful check', () => {
    const report = normalizeQualityReport({ report_id: 'r1', status: 'passed' } as QualityReport);
    expect(report?.status).toBe('incomplete');
    expect(report?.findings).toEqual([]);
    expect(report?.error).toContain('仍可继续创作');
  });

  it.each([null, {}, { report_id: 'partial' }])('allows leaving the legacy quality stage with report %s', value => {
    const markup = renderToStaticMarkup(<QualityReviewStage report={value as QualityReport | null} isLoading={false} error={null} />);
    expect(markup).toContain('质量检查未完成');
    expect(markup).toContain('返回游戏数据 · 继续创作');
  });
});
