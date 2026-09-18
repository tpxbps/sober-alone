import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it } from 'vitest';
import { WorkflowFooterMessage } from './WorkflowFooterMessage';
it('keeps idle and short operations free of footer messages', () => {
  expect(renderToStaticMarkup(<WorkflowFooterMessage isWorking={false} />)).toBe('');
  expect(renderToStaticMarkup(<WorkflowFooterMessage isWorking />)).toBe('');
});
