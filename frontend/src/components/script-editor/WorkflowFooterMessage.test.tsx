import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  WORKFLOW_MOTTO,
  WORKFLOW_WAIT_MESSAGE,
  WorkflowFooterMessage,
} from "./WorkflowFooterMessage";

describe("WorkflowFooterMessage", () => {
  it("keeps the regular footer outside a running node", () => {
    expect(renderToStaticMarkup(<WorkflowFooterMessage isWorking={false} />)).toContain(
      WORKFLOW_MOTTO
    );
  });

  it("starts a typed waiting hint with the complete accessible message", () => {
    const markup = renderToStaticMarkup(<WorkflowFooterMessage isWorking />);

    expect(markup).toContain(`aria-label="${WORKFLOW_WAIT_MESSAGE}"`);
    expect(markup).not.toContain("审稿修订会连续完成");
  });
});
