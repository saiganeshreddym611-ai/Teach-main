import { readFileSync } from "node:fs";
import { join } from "node:path";
import assert from "node:assert/strict";
import test from "node:test";

import { dispatch, parseSseBlock } from "../lib/sse.ts";

const fixturesDir = join(import.meta.dirname, "fixtures", "sse");

function readFixture(name: string): string {
  return readFileSync(join(fixturesDir, name), "utf8").trim();
}

function blocksFromFixture(name: string): string[] {
  return readFixture(name)
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
}

test("parseSseBlock handles basic grade/text/done SSE message blocks", () => {
  const blocks = blocksFromFixture("today.txt");
  assert.equal(blocks.length, 3);

  const grade = parseSseBlock(blocks[0]);
  assert.ok(grade);
  assert.equal(grade?.kind, "grade");
  assert.equal((grade?.data as { summary: string }).summary, "Good baseline.");

  const text = parseSseBlock(blocks[1]);
  assert.ok(text);
  assert.equal(text?.kind, "text");
  assert.deepEqual((text?.data as { delta: string }), { delta: "We recognise revenue when control transfers." });

  const done = parseSseBlock(blocks[2]);
  assert.ok(done);
  assert.equal(done?.kind, "done");
  assert.equal((done?.data as { phase: string }).phase, "INSTRUCT");
  assert.equal(((done?.data as { ledger_delta: Array<{ id: string }> }).ledger_delta[0]?.id), "l-1");
});

test("dispatch handles grade claims/omissions and done citations/grounding", () => {
  const blocks = blocksFromFixture("v2.txt");
  assert.equal(blocks.length, 2);

  let gradePayload: unknown = null;
  let donePayload: unknown = null;

  dispatch(blocks[0], {
    onGrade: (g) => {
      gradePayload = g;
    },
  });
  assert.ok(gradePayload);
  assert.equal((gradePayload as { summary: string }).summary, "Needs a clearer link to the contract asset.");
  assert.equal(((gradePayload as { claims: Array<{ verdict: string }> }).claims[0]?.verdict), "supported");
  assert.equal(((gradePayload as { omissions: Array<{ node_id: string }> }).omissions[0]?.node_id), "ind_as_115.step_3");

  dispatch(blocks[1], {
    onDone: (d) => {
      donePayload = d;
    },
  });
  assert.ok(donePayload);
  assert.equal((donePayload as { phase: string }).phase, "TASK");
  assert.equal(((donePayload as { citations: Array<{ passage_id: string }> }).citations[0]?.passage_id), "p-3");
  assert.equal(((donePayload as { grounding: Array<{ passage_id: string }> }).grounding[0]?.passage_id), "p-3");
});

test("unknown event kinds are ignored without throwing", () => {
  const blocks = blocksFromFixture("unknown.txt");
  assert.equal(blocks.length, 3);

  let gradeCalled = 0;
  let textCalled = 0;
  let doneCalled = 0;
  let scopeCalled = 0;
  let taskCalled = 0;
  let taskResultCalled = 0;
  let skillCalled = 0;
  let practiceCalled = 0;

  assert.doesNotThrow(() => {
    for (const block of blocks) {
      dispatch(block, {
        onGrade: () => {
          gradeCalled += 1;
        },
        onText: () => {
          textCalled += 1;
        },
        onDone: () => {
          doneCalled += 1;
        },
        onScope: () => {
          scopeCalled += 1;
        },
        onTask: () => {
          taskCalled += 1;
        },
        onTaskResult: () => {
          taskResultCalled += 1;
        },
        onSkill: () => {
          skillCalled += 1;
        },
        onPractice: () => {
          practiceCalled += 1;
        },
      });
    }
  });

  assert.equal(gradeCalled, 1);
  assert.equal(textCalled, 1);
  assert.equal(doneCalled, 0);
  assert.equal(scopeCalled, 0);
  assert.equal(taskCalled, 0);
  assert.equal(taskResultCalled, 0);
  assert.equal(skillCalled, 0);
  assert.equal(practiceCalled, 0);
});
