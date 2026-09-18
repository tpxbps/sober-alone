import type { ModelHealthResponse } from '@/types/capabilities';

export function modelHealthMessage(result: ModelHealthResponse, manual = false): string {
  if (result.probing) return '';
  const serviceError = result.service_error ?? result.models.find(item => item.error_code)?.error_code;
  if (serviceError === 'probe_auth') return '测速服务鉴权失败，需维护者处理；这不代表各模型不可用，可继续使用当前配置。';
  if (serviceError === 'probe_account') return '测速服务账户暂不可用，需维护者处理；可继续使用当前配置。';
  if (manual && result.retry_after_seconds) return `刚完成一次测速，请 ${result.retry_after_seconds} 秒后重新测试。`;
  const failed = result.models.filter(model => !['normal', 'slow'].includes(model.status));
  if (failed.length) return failed.length === result.models.length
    ? '本次测速未取得完整结果，可继续使用当前配置并稍后重试。'
    : '部分模型测速未完成，可继续使用当前配置并稍后重试。';
  if (!result.models.length) return manual ? '暂无可测速的模型。' : '';
  return manual ? '测速已更新' : '';
}
