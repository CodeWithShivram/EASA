import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/client";
import type { ChatApi, Conversation, Message, Source } from "@/lib/api/conversations";

import { ChatPage } from "./ChatPage";

// One router object, as in Next.js (a new object per render would re-run effects).
const { replace, router } = vi.hoisted(() => {
  const replace = vi.fn();
  return { replace, router: { replace } };
});
vi.mock("next/navigation", () => ({ useRouter: () => router }));

const SOURCE: Source = {
  label: "S1",
  citation: {
    document_id: "doc-1",
    filename: "leave_policy.txt",
    page_number: 2,
    section: "Annual leave",
    chunk_index: 0,
    char_start: 0,
    char_end: 60,
  },
};

function message(overrides: Partial<Message>): Message {
  return {
    id: crypto.randomUUID(),
    position: 0,
    role: "user",
    content: null,
    status: null,
    reason: null,
    sources: [],
    model_id: null,
    created_at: "2026-11-18T10:00:00Z",
    ...overrides,
  };
}

const ANSWERED: Message[] = [
  message({ position: 0, role: "user", content: "How many leave days?" }),
  message({
    position: 1,
    role: "assistant",
    content: "Employees get 25 days of annual leave [S1].",
    status: "answered",
    sources: [SOURCE],
  }),
];

function fakeApi(overrides: Partial<ChatApi> = {}): ChatApi {
  let messages: Message[] = [];
  const conversation = (): Conversation => ({
    id: "c1",
    created_at: "2026-11-18T09:00:00Z",
    updated_at: "2026-11-18T09:00:00Z",
    messages,
  });
  return {
    list: vi.fn(async () => [
      {
        id: "c1",
        created_at: "2026-11-18T09:00:00Z",
        updated_at: "2026-11-18T09:00:00Z",
        messages: messages.length,
      },
    ]),
    create: vi.fn(async () => ({
      id: "c1",
      created_at: "2026-11-18T09:00:00Z",
      updated_at: "2026-11-18T09:00:00Z",
      messages: 0,
    })),
    get: vi.fn(async () => conversation()),
    ask: vi.fn(async () => {
      messages = ANSWERED;
      return {
        conversation_id: "c1",
        turn: 1,
        answer: {
          status: "answered" as const,
          answer: "Employees get 25 days of annual leave [S1].",
          reason: null,
          sources: [
            { ...SOURCE, text: "Full-time employees receive 25 days of paid annual leave." },
          ],
          retrieved: 3,
          model_id: "fake",
        },
      };
    }),
    remove: vi.fn(async () => undefined),
    chunkText: vi.fn(async () => "Stored chunk text."),
    ...overrides,
  };
}

beforeEach(() => replace.mockClear());

async function openConversation(api: ChatApi) {
  const user = userEvent.setup();
  render(<ChatPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /question/ }));
  return user;
}

describe("ChatPage", () => {
  it("explains the page before a conversation is chosen", async () => {
    render(<ChatPage api={fakeApi({ list: vi.fn(async () => []) })} />);

    expect(
      await screen.findByText("No conversations yet. Start one with New."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Answers cite their sources/)).toBeInTheDocument();
  });

  it("asks a question, shows the cited answer and the source text the model saw", async () => {
    const api = fakeApi();
    const user = await openConversation(api);

    await user.type(screen.getByLabelText("Your question"), "How many leave days?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(api.ask).toHaveBeenCalledWith("c1", "How many leave days?");
    expect(await screen.findByText(/Employees get 25 days/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show source S1: leave_policy.txt" }));
    const panel = screen.getByRole("complementary", { name: "Source S1" });
    expect(within(panel).getByText(/page 2 · Annual leave · part 1/)).toBeInTheDocument();
    expect(
      within(panel).getByText("Full-time employees receive 25 days of paid annual leave."),
    ).toBeInTheDocument();
    expect(api.chunkText).not.toHaveBeenCalled(); // the fresh answer carried the text
  });

  it("loads the text of an older answer's source, and says when it is no longer visible", async () => {
    const api = fakeApi({
      get: vi.fn(async () => ({
        id: "c1",
        created_at: "2026-11-18T09:00:00Z",
        updated_at: "",
        messages: ANSWERED,
      })),
      chunkText: vi.fn(async () => {
        throw new ApiError("http", "Document not found.", { status: 404 });
      }),
    });
    const user = await openConversation(api);

    await user.click(
      await screen.findByRole("button", { name: "Show source S1: leave_policy.txt" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer available to you");
    expect(api.chunkText).toHaveBeenCalledWith(SOURCE.citation);
  });

  it("shows insufficient evidence as such, never as an answer", async () => {
    const api = fakeApi({
      get: vi.fn(async () => ({
        id: "c1",
        created_at: "2026-11-18T09:00:00Z",
        updated_at: "",
        messages: [
          message({ role: "user", content: "What is the dress code?" }),
          message({
            position: 1,
            role: "assistant",
            status: "insufficient_evidence",
            reason: "model_declined",
          }),
        ],
      })),
    });
    await openConversation(api);

    expect(await screen.findByText("No supported answer")).toBeInTheDocument();
    expect(
      screen.getByText("The documents you can access do not answer this question."),
    ).toBeInTheDocument();
  });

  it("shows progress while waiting and explains API errors", async () => {
    let fail: (error: unknown) => void = () => undefined;
    const api = fakeApi({
      ask: vi.fn(
        () =>
          new Promise<never>((_resolve, reject) => {
            fail = reject;
          }),
      ),
    });
    const user = await openConversation(api);

    await user.type(screen.getByLabelText("Your question"), "Another question");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByRole("status")).toHaveTextContent("Searching your documents");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    fail(new ApiError("http", "Full.", { status: 409, code: "conversation_full" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("limit of 50 questions");
  });

  it("sends the user to sign in when the session has ended", async () => {
    render(
      <ChatPage
        api={fakeApi({
          list: vi.fn(async () => {
            throw new ApiError("http", "Authentication required.", { status: 401 });
          }),
        })}
      />,
    );

    await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("deletes a conversation only after confirmation", async () => {
    const api = fakeApi();
    const user = userEvent.setup();
    render(<ChatPage api={api} />);

    await user.click(await screen.findByRole("button", { name: /Delete conversation/ }));
    await user.click(screen.getByRole("button", { name: "Keep" }));
    expect(api.remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /Delete conversation/ }));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(api.remove).toHaveBeenCalledWith("c1");
  });

  it("starts a new conversation", async () => {
    const api = fakeApi({ list: vi.fn(async () => []) });
    const user = userEvent.setup();
    render(<ChatPage api={api} />);

    await user.click(await screen.findByRole("button", { name: "New" }));

    expect(api.create).toHaveBeenCalled();
    expect(await screen.findByLabelText("Your question")).toBeInTheDocument();
  });
});
