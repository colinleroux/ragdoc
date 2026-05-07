import Alpine from "alpinejs";
import "./main.css";

function apiErrorMessage(error) {
  if (error && typeof error === "object" && "detail" in error) {
    return error.detail;
  }
  return "Request failed.";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 504) {
      throw new Error("The model request timed out before Ollama returned an answer.");
    }
    if (response.status >= 500) {
      throw new Error(`Server error ${response.status}. Check the container logs for details.`);
    }
    throw new Error(apiErrorMessage(data));
  }
  return data;
}

Alpine.data("pipelineStatus", (initialConfig) => ({
  config: initialConfig,
  draftConfig: {
    docs_path: initialConfig.docs_path || "",
    collection: initialConfig.collection || "",
    model: initialConfig.model || "",
    embed_model: initialConfig.embed_model || "",
    ollama_url: initialConfig.ollama_url || "",
    qdrant_url: initialConfig.qdrant_url || "",
  },
  modelOptions: { installed: [], recommended: { generation: [], embedding: [] } },
  savedPrompts: [],
  pipelineCheck: null,
  ollamaRuntime: null,
  stats: {},
  docs: { docs: [], count: 0 },
  corpus: { files: [], count: 0 },
  selectedSource: "",
  chunks: [],
  chunksLoading: false,
  question: "",
  answerStyle: "auto",
  strictness: "balanced",
  reasoningMode: "grounded",
  topK: 5,
  maxSources: 5,
  minSemanticScore: 0.35,
  answer: "",
  sources: [],
  answerMeta: {},
  currentRun: null,
  selectedPromptId: "",
  askRuns: [],
  askRunsSortKey: "created_at",
  askRunsSortDir: "desc",
  notice: "",
  noticeType: "success",
  activeTab: "setup",
  showCorpusConfig: false,
  showChunkPreview: true,
  setupProgress: {},
  setupEvents: null,
  loading: false,
  configSaving: false,
  configChecking: false,
  setupRunning: false,
  ingestRunning: false,
  resetRunning: false,
  askRunning: false,

  async init() {
    await this.refresh();
    await this.loadModelOptions();
    await this.loadSavedPrompts();
  },

  setNotice(message, type = "success") {
    this.notice = message;
    this.noticeType = type;
  },

  setTab(tab) {
    this.activeTab = tab;
  },

  sortAskRunsBy(key) {
    if (this.askRunsSortKey === key) {
      this.askRunsSortDir = this.askRunsSortDir === "asc" ? "desc" : "asc";
      return;
    }
    this.askRunsSortKey = key;
    this.askRunsSortDir = key === "question" || key === "style" || key === "model" || key === "rating" ? "asc" : "desc";
  },

  sortIndicator(key) {
    if (this.askRunsSortKey !== key) {
      return "";
    }
    return this.askRunsSortDir === "asc" ? " ^" : " v";
  },

  sortedAskRuns() {
    const key = this.askRunsSortKey;
    const dir = this.askRunsSortDir === "asc" ? 1 : -1;
    const valueFor = (run) => {
      switch (key) {
        case "question":
          return (run.input?.question || run.name || "").toLowerCase();
        case "style":
          return (run.input?.answer_style || "").toLowerCase();
        case "model":
          return (run.model || "").toLowerCase();
        case "top_score":
          return Number(run.meta?.top_semantic_score ?? -1);
        case "latency":
          return Number(run.latency_ms ?? -1);
        case "rating":
          return Number(run.evaluation?.satisfactory === null || run.evaluation?.satisfactory === undefined ? -1 : run.evaluation.satisfactory ? 1 : 0);
        case "created_at":
        default:
          return Date.parse(run.created_at || 0) || 0;
      }
    };

    return [...this.askRuns].sort((left, right) => {
      const leftValue = valueFor(left);
      const rightValue = valueFor(right);
      if (leftValue < rightValue) {
        return -1 * dir;
      }
      if (leftValue > rightValue) {
        return 1 * dir;
      }
      return 0;
    });
  },

  formatBytes(value) {
    if (!Number.isFinite(value) || value <= 0) {
      return "-";
    }

    const units = ["B", "KB", "MB", "GB"];
    let size = value;
    let unitIndex = 0;
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex += 1;
    }

    const precision = size >= 10 || unitIndex === 0 ? 0 : 1;
    return `${size.toFixed(precision)} ${units[unitIndex]}`;
  },

  async refresh() {
    this.loading = true;
    try {
      const [stats, docs, corpus, askRuns, pipelineConfig] = await Promise.all([
        fetchJson("/api/stats"),
        fetchJson("/api/ingested-docs"),
        fetchJson("/api/corpus-files"),
        fetchJson("/api/ask-runs?limit=12"),
        fetchJson("/api/pipeline-config"),
      ]);
      this.stats = stats;
      this.docs = docs;
      this.corpus = corpus;
      this.askRuns = askRuns.runs || [];
      this.config = pipelineConfig;
      this.draftConfig = {
        docs_path: pipelineConfig.docs_path || "",
        collection: pipelineConfig.collection || "",
        model: pipelineConfig.model || "",
        embed_model: pipelineConfig.embed_model || "",
        ollama_url: pipelineConfig.ollama_url || "",
        qdrant_url: pipelineConfig.qdrant_url || "",
      };
      if (this.selectedSource) {
        await this.loadChunks({ source: this.selectedSource }, false, false);
      }
      await this.loadOllamaRuntime();
      this.setNotice("Pipeline status refreshed.");
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.loading = false;
    }
  },

  async loadModelOptions() {
    try {
      this.modelOptions = await fetchJson("/api/pipeline-model-options");
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async loadSavedPrompts() {
    try {
      const result = await fetchJson("/api/prompts");
      this.savedPrompts = result.prompts || [];
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async loadOllamaRuntime() {
    try {
      this.ollamaRuntime = await fetchJson("/api/ollama-runtime");
    } catch (error) {
      this.ollamaRuntime = {
        reachable: false,
        gpu_state: "unknown",
        note: error.message,
        running_models: [],
        running_count: 0,
        total_vram_bytes: 0,
      };
    }
  },

  usePipelineModel(kind, name) {
    if (kind === "generation") {
      this.draftConfig.model = name;
      return;
    }
    if (kind === "embedding") {
      this.draftConfig.embed_model = name;
    }
  },

  applySelectedPrompt() {
    const prompt = this.savedPrompts.find((item) => String(item.id) === String(this.selectedPromptId));
    if (!prompt) {
      this.setNotice("Select a saved prompt first.", "error");
      return;
    }

    if (this.question.trim() && this.question.trim() !== prompt.template.trim()) {
      const confirmed = window.confirm(`Replace the current question with the saved prompt "${prompt.name}"?`);
      if (!confirmed) {
        return;
      }
    }

    this.question = prompt.template || "";
    const defaults = prompt.query_defaults || {};
    this.answerStyle = defaults.answer_style || "auto";
    this.topK = defaults.top_k ?? 5;
    this.maxSources = defaults.max_sources ?? 5;
    this.strictness = defaults.strictness || "balanced";
    this.minSemanticScore = defaults.min_semantic_score ?? 0.35;
    this.reasoningMode = defaults.reasoning_mode || "grounded";
    this.setNotice(`Loaded prompt "${prompt.name}" into Query.`);
  },

  clearSelectedPrompt() {
    this.selectedPromptId = "";
    this.setNotice("Using an ad hoc question instead of a saved prompt.");
  },

  evaluationLabel(run) {
    if (!run?.evaluation || run.evaluation.satisfactory === null || run.evaluation.satisfactory === undefined) {
      return "-";
    }
    return run.evaluation.satisfactory ? "Satisfactory" : "Not satisfactory";
  },

  applyUpdatedRun(updatedRun) {
    this.askRuns = this.askRuns.map((run) => (run.id === updatedRun.id ? updatedRun : run));
    if (this.currentRun?.id === updatedRun.id) {
      this.currentRun = { ...this.currentRun, ...updatedRun };
    }
  },

  async setRunEvaluation(run, satisfactory) {
    try {
      const result = await fetchJson(`/api/ask-runs/${run.id}/evaluation`, {
        method: "PUT",
        body: JSON.stringify({
          satisfactory,
          notes: run.evaluation?.notes || "",
        }),
      });
      this.applyUpdatedRun(result);
      this.setNotice(`Saved evaluation for run ${run.id}.`);
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async editRunNotes(run) {
    const initialNotes = run.evaluation?.notes || "";
    const notes = window.prompt("Add evaluation notes for this captured answer.", initialNotes);
    if (notes === null) {
      return;
    }

    try {
      const result = await fetchJson(`/api/ask-runs/${run.id}/evaluation`, {
        method: "PUT",
        body: JSON.stringify({
          satisfactory: run.evaluation?.satisfactory ?? null,
          notes,
        }),
      });
      this.applyUpdatedRun(result);
      this.setNotice(`Saved notes for run ${run.id}.`);
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async savePipelineConfig() {
    this.configSaving = true;
    this.setNotice("Saving pipeline settings.");
    try {
      const result = await fetchJson("/api/pipeline-config", {
        method: "PUT",
        body: JSON.stringify(this.draftConfig),
      });
      this.config = result;
      await this.refresh();
      await this.loadModelOptions();
      this.setNotice("Pipeline settings saved. If you changed the embedding model or collection, reset and re-ingest before comparing answers.");
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.configSaving = false;
    }
  },

  async checkPipelineConfig() {
    this.configChecking = true;
    this.setNotice("Checking pipeline settings.");
    try {
      this.pipelineCheck = await fetchJson("/api/pipeline-config/check", {
        method: "POST",
        body: JSON.stringify(this.draftConfig),
      });
      const ollama = this.pipelineCheck.ollama || {};
      const qdrant = this.pipelineCheck.qdrant || {};
      const docs = this.pipelineCheck.docs_path || {};
      const summary = [
        docs.exists ? "docs path ok" : "docs path missing",
        ollama.reachable ? "ollama reachable" : "ollama unreachable",
        qdrant.reachable ? "qdrant reachable" : "qdrant unreachable",
      ];
      this.setNotice(`Pipeline check complete: ${summary.join(", ")}.`);
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.configChecking = false;
    }
  },

  async resetPipelineConfig() {
    const confirmed = window.confirm("Reset pipeline settings back to the compose or environment defaults?");
    if (!confirmed) {
      return;
    }

    this.configSaving = true;
    try {
      const result = await fetchJson("/api/pipeline-config", { method: "DELETE" });
      this.config = result;
      await this.refresh();
      await this.loadModelOptions();
      this.setNotice("Pipeline settings reset to defaults.");
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.configSaving = false;
    }
  },

  setupModels() {
    if (this.setupEvents) {
      this.setupEvents.close();
    }

    this.setupRunning = true;
    this.setupProgress = { status: "starting", model_percent: 0, overall_percent: 0 };
    this.setNotice("Pulling required models. Progress will update here.");

    const events = new EventSource("/api/setup-models/stream");
    this.setupEvents = events;

    events.addEventListener("start", () => {
      this.setupProgress = { status: "starting", model_percent: 0, overall_percent: 0 };
    });

    events.addEventListener("progress", (event) => {
      this.setupProgress = JSON.parse(event.data);
    });

    events.addEventListener("done", (event) => {
      const result = JSON.parse(event.data);
      this.setupProgress = {
        ...this.setupProgress,
        status: "ready",
        model_percent: 100,
        overall_percent: 100,
      };
      this.setNotice(`Models ready: ${result.embed_model} and ${result.model_name}.`);
      this.setupRunning = false;
      events.close();
      this.setupEvents = null;
    });

    events.addEventListener("failed", (event) => {
      const result = JSON.parse(event.data);
      this.setNotice(result.detail || "Model setup failed.", "error");
      this.setupProgress = { ...this.setupProgress, status: "failed" };
      this.setupRunning = false;
      events.close();
      this.setupEvents = null;
    });

    events.onerror = () => {
      this.setNotice("Model setup stream disconnected.", "error");
      this.setupProgress = { ...this.setupProgress, status: "disconnected" };
      this.setupRunning = false;
      events.close();
      this.setupEvents = null;
    };
  },

  async loadChunks(doc, announce = true, switchTab = true) {
    const source = doc?.source || "";
    if (!source) {
      return;
    }

    this.selectedSource = source;
    if (switchTab) {
      this.activeTab = "inputs";
    }
    this.showChunkPreview = true;
    this.chunksLoading = true;
    try {
      const params = new URLSearchParams({ source, limit: "100" });
      const result = await fetchJson(`/api/chunks?${params.toString()}`);
      this.chunks = result.chunks || [];
      if (announce) {
        this.setNotice(`Loaded ${result.count} chunks for ${source}.`);
      }
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.chunksLoading = false;
    }
  },

  async openRetrievedChunk(source) {
    const chunkId = source?.document_chunk_id;
    if (!chunkId) {
      this.setNotice("This retrieved source is not linked to a SQLite chunk.", "error");
      return;
    }

    this.chunksLoading = true;
    try {
      const chunk = await fetchJson(`/api/chunks/${chunkId}`);
      this.activeTab = "inputs";
      this.selectedSource = chunk.source;
      this.chunks = [chunk];
      this.showChunkPreview = true;
      this.setNotice(`Opened chunk ${chunk.id} from ${chunk.source} in Inputs.`);
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.chunksLoading = false;
    }
  },

  async ingest() {
    this.ingestRunning = true;
    this.activeTab = "inputs";
    this.setNotice("Running ingestion.");
    try {
      const result = await fetchJson("/api/ingest", { method: "POST" });
      this.activeTab = "query";
      this.setNotice(`Ingested ${result.files} files, ${result.chunks} chunks, and ${result.embeddings} embeddings.`);
      await this.refresh();
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.ingestRunning = false;
    }
  },

  async resetIngestion() {
    const confirmed = window.confirm("Reset all ingested documents, chunks, embeddings, and the Qdrant collection? Source files in docs are not deleted.");
    if (!confirmed) {
      return;
    }

    this.resetRunning = true;
    this.setNotice("Resetting ingestion state.");
    try {
      const result = await fetchJson("/api/reset-ingestion", { method: "POST" });
      this.selectedSource = "";
      this.chunks = [];
      this.answer = "";
      this.sources = [];
      this.answerMeta = {};
      this.currentRun = null;
      this.setNotice(`Reset complete: removed ${result.sources_deleted} sources, ${result.chunks_deleted} chunks, and ${result.embeddings_deleted} embeddings.`);
      await this.refresh();
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.resetRunning = false;
    }
  },

  async removeIngestedDoc(source) {
    const confirmed = window.confirm(`Remove ingested document "${source}" from the ledger and vector store? The file in docs will not be deleted.`);
    if (!confirmed) {
      return;
    }

    try {
      const params = new URLSearchParams({ source });
      const result = await fetchJson(`/api/ingested-docs?${params.toString()}`, { method: "DELETE" });
      if (this.selectedSource === source) {
        this.selectedSource = "";
        this.chunks = [];
      }
      this.setNotice(`Removed ${result.source} with ${result.chunks_deleted} chunks and ${result.embeddings_deleted} embeddings.`);
      await this.refresh();
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async ask() {
    if ((this.stats.embeddings ?? 0) < 1) {
      this.activeTab = "inputs";
      this.setNotice("Ingest documents before asking; no embeddings are available yet.", "error");
      return;
    }

    this.askRunning = true;
    this.activeTab = "query";
    this.answer = "";
    this.sources = [];
    this.answerMeta = {};
    this.currentRun = null;
    this.setNotice("Asking model. This can take a little while.");
    try {
      const result = await fetchJson("/api/ask", {
        method: "POST",
        body: JSON.stringify({
          question: this.question,
          prompt_id: this.selectedPromptId || null,
          top_k: this.topK,
          max_sources: this.maxSources,
          min_semantic_score: this.minSemanticScore,
          answer_style: this.answerStyle,
          strictness: this.strictness,
          reasoning_mode: this.reasoningMode,
          debug: false,
        }),
      });
      this.answer = result.answer;
      this.sources = result.sources || [];
      this.answerMeta = result.meta || {};
      this.currentRun = result.run || null;
      await this.refresh();
      this.activeTab = "answers";
      this.setNotice(this.currentRun ? `Answer generated and captured as run ${this.currentRun.id}.` : "Answer generated.");
    } catch (error) {
      this.setNotice(error.message, "error");
    } finally {
      this.askRunning = false;
    }
  },

  async loadCapturedRun(runId) {
    try {
      this.activeTab = "answers";
      const run = await fetchJson(`/api/ask-runs/${runId}`);
      this.currentRun = run;
      this.selectedPromptId = run.prompt_id && run.prompt_name !== "Pipeline Ask" ? String(run.prompt_id) : "";
      this.question = run.input?.question || "";
      this.answerStyle = run.input?.answer_style || "auto";
      this.strictness = run.input?.strictness || "balanced";
      this.reasoningMode = run.input?.reasoning_mode || "grounded";
      this.topK = run.input?.top_k || 5;
      this.maxSources = run.input?.max_sources || 5;
      this.minSemanticScore = run.input?.min_semantic_score ?? 0.35;
      this.answer = run.answer || "";
      this.sources = run.sources || [];
      this.answerMeta = run.meta || {};
      const chunkArtifact = (run.artifacts || []).find((artifact) => artifact.artifact_type === "retrieved_chunks");
      if (chunkArtifact?.content?.length) {
        this.chunks = chunkArtifact.content;
        this.selectedSource = this.chunks[0].source;
        this.showChunkPreview = true;
      }
      this.setNotice(`Loaded captured run ${run.id}.`);
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },

  async removeCapturedRun(run) {
    const label = run?.input?.question || run?.name || `run ${run?.id}`;
    const confirmed = window.confirm(`Remove captured answer "${label}"?`);
    if (!confirmed) {
      return;
    }

    try {
      await fetchJson(`/api/ask-runs/${run.id}`, { method: "DELETE" });
      if (this.currentRun?.id === run.id) {
        this.currentRun = null;
        this.answer = "";
        this.sources = [];
        this.answerMeta = {};
      }
      this.setNotice(`Removed captured run ${run.id}.`);
      await this.refresh();
    } catch (error) {
      this.setNotice(error.message, "error");
    }
  },
}));

window.Alpine = Alpine;
Alpine.start();
