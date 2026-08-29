import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ContentPanel } from './ContentPanel'

describe('ContentPanel pending workflow state', () => {
  it('renders the outline loading state while a new workflow is starting', () => {
    const markup = renderToStaticMarkup(
      <ContentPanel
        interruptInfo={null}
        currentStep="generate_outline"
        isComplete={false}
        isLoading={false}
        isStarting
        error={null}
        scriptTitle=""
        workflowState={null}
        assetProgress={null}
        convertProgress={null}
        viewingCheckpoint={null}
        onConfirm={async () => undefined}
        onConfirmGameData={async () => undefined}
        onConfirmAssetPlan={async () => undefined}
        onConfirmReviewFinal={async () => undefined}
        onRegenerate={async () => undefined}
        onRegenerateReviewFinal={async () => undefined}
        onStart={() => undefined}
        onBack={() => undefined}
        onRetryAsset={async () => undefined}
        onRetryConvert={async () => undefined}
      />,
    )

    expect(markup).toContain('正在构思剧本大纲...')
    expect(markup).toContain('单个节点可能耗时数分钟')
    expect(markup).toContain('返回大厅稍后继续')
    expect(markup).not.toContain('流程中断')
  })

  it('offers one full conversion rerun when a structured task failed', () => {
    const markup = renderToStaticMarkup(
      <ContentPanel
        interruptInfo={null}
        currentStep="convert_to_game_data"
        isComplete={false}
        isLoading={false}
        isStarting={false}
        error={null}
        scriptTitle="测试剧本"
        workflowState={null}
        assetProgress={null}
        convertProgress={{
          isComplete: false,
          phases: [
            {
              id: 'game_flow',
              label: '线索阶段数据',
              tech: 'LLM',
              tasks: [
                {
                  id: 'game_flow',
                  label: '生成线索阶段系统消息',
                  status: 'failed',
                },
              ],
            },
          ],
        }}
        viewingCheckpoint={null}
        onConfirm={async () => undefined}
        onConfirmGameData={async () => undefined}
        onConfirmAssetPlan={async () => undefined}
        onConfirmReviewFinal={async () => undefined}
        onRegenerate={async () => undefined}
        onRegenerateReviewFinal={async () => undefined}
        onStart={() => undefined}
        onBack={() => undefined}
        onRetryAsset={async () => undefined}
        onRetryConvert={async () => undefined}
      />,
    )

    expect(markup).toContain('重新执行结构化转换')
    expect(markup).toContain('避免只更新进度、遗漏数据合并')
    expect(markup).not.toContain('转换任务 game_flow 重试')
  })
})
