(() => {
  const body = document.body;
  const sessionId = body.dataset.sessionId;
  const newSession = document.getElementById("new-session");
  const composer = document.getElementById("composer");
  const input = document.getElementById("message-input");
  const deepMode = document.getElementById("deep-mode");
  const eventStrip = document.getElementById("event-strip");
  const eventLabel = document.getElementById("event-label");
  const runStatus = document.getElementById("run-status");

  const icons = () => window.lucide && window.lucide.createIcons();
  window.addEventListener("load", icons);

  const sidebarToggle = document.getElementById("sidebar-toggle");
  if (localStorage.getItem("learningloop.sidebar-collapsed") === "1") {
    body.classList.add("sidebar-collapsed");
  }
  sidebarToggle?.addEventListener("click", () => {
    const collapsed = body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("learningloop.sidebar-collapsed", collapsed ? "1" : "0");
  });

  const historyToggle = document.getElementById("session-history-toggle");
  const sessionList = document.querySelector(".session-list");
  historyToggle?.addEventListener("click", () => {
    if (!sessionList) return;
    const expanded = sessionList.classList.toggle("show-all");
    historyToggle.querySelector("span").textContent = expanded ? "收起历史会话" : "查看历史会话";
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");
    });
  });

  const createSession = async () => {
    const response = await fetch("/api/v1/sessions", { method: "POST" });
    if (!response.ok) return;
    const session = await response.json();
    window.location.assign(`/?session_id=${session.id}`);
  };
  [newSession, document.getElementById("new-session-sidebar"), document.getElementById("new-session-welcome")]
    .filter(Boolean)
    .forEach((button) => button.addEventListener("click", createSession));

  const setRunning = (running, label = "正在处理") => {
    if (eventStrip) eventStrip.hidden = !running;
    if (eventLabel) eventLabel.textContent = label;
    runStatus.textContent = running ? label : "本地运行";
    if (input) input.disabled = running;
    const submit = composer?.querySelector("button[type=submit]");
    if (submit) submit.disabled = running;
  };

  const eventNames = [
    "run_started", "context", "thought", "action", "observation",
    "approval_required", "action_required", "action_decided", "plan_applied", "done", "error"
  ];

  const appendMessage = (role, content) => {
    const messages = document.getElementById("messages");
    if (!messages || !content) return;
    messages.querySelector(".empty-state")?.remove();
    const article = document.createElement("article");
    article.className = `message ${role}`;
    const label = role === "user" ? "你" : "学习助手";
    const icon = role === "user" ? "user-round" : "graduation-cap";
    const time = new Date().toLocaleString("zh-CN", { hour12: false }).slice(0, 16);
    article.innerHTML = `<div class="message-avatar"><i data-lucide="${icon}"></i></div><div class="message-body"><div class="message-role">${label}<time>${escapeHtml(time)}</time></div><div class="message-content"></div></div>`;
    article.querySelector(".message-content").textContent = content;
    messages.appendChild(article);
    messages.scrollTop = messages.scrollHeight;
    icons();
  };

  const appendSystemNotice = (message, error = false) => {
    const composer = document.getElementById("composer");
    if (!composer) return;
    const notice = document.createElement("div");
    notice.className = `system-notice${error ? " error" : ""}`;
    notice.textContent = message;
    composer.before(notice);
  };

  const setAgentRole = (value) => {
    const runtimeCard = document.querySelector(".runtime-card");
    if (!runtimeCard) return;
    let role = document.getElementById("runtime-agent-role");
    if (!role) {
      const row = document.createElement("div");
      row.innerHTML = '<span>运行入口</span><strong id="runtime-agent-role"></strong>';
      runtimeCard.prepend(row);
      role = row.querySelector("strong");
    }
    if (role) role.textContent = value || "interactive";
  };

  const insertPendingAction = async (actionId) => {
    if (!actionId || document.querySelector(`[data-action-id="${CSS.escape(actionId)}"]`)) return;
    const response = await fetch(`/api/v1/actions/${actionId}`);
    if (!response.ok) return;
    const composer = document.getElementById("composer");
    if (!composer) return;
    composer.insertAdjacentHTML("beforebegin", renderActionCard(await response.json()));
    icons();
  };

  const watchEvents = (afterEventId = 0) => {
    if (!sessionId) return;
    const source = new EventSource(`/api/v1/sessions/${sessionId}/events?after=${afterEventId}`);
    let cursor = afterEventId;
    let stopped = false;
    eventNames.forEach((name) => source.addEventListener(name, (event) => {
      cursor = Number(event.lastEventId || cursor);
      const data = JSON.parse(event.data);
      const labels = {
        run_started: `加载 ${data.payload.skill || "Skill"}`,
        context: "整理上下文",
        thought: "模型推理",
        action: `调用 ${data.payload.tool || "工具"}`,
        observation: "校验工具结果",
        approval_required: "等待计划审批",
        action_required: "等待操作确认",
        action_decided: "操作已处理",
        plan_applied: "计划已生效",
        done: "本轮完成",
        error: "运行失败"
      };
      if (name === "done" && data.payload?.answer) appendMessage("assistant", data.payload.answer);
      if (name === "action_required") insertPendingAction(data.payload?.action_id);
      if (data.payload?.stage) {
        const stage = document.getElementById("runtime-stage");
        if (stage) stage.textContent = data.payload.stage;
      }
      const stageForEvent = {
        run_started: "received",
        context: "context_ready",
        action: "tool_call",
        observation: "effect_applied",
        action_required: "awaiting_action",
        action_decided: "effect_applied",
        plan_applied: "completed",
        done: "completed",
        error: "failed",
      };
      if (!data.payload?.stage && stageForEvent[name]) {
        const stage = document.getElementById("runtime-stage");
        if (stage) stage.textContent = stageForEvent[name];
      }
      if (data.payload?.skill) {
        const skill = document.getElementById("runtime-skill");
        if (skill) skill.textContent = data.payload.skill;
      }
      if (data.payload?.agent_role) setAgentRole(data.payload.agent_role);
      if (name === "error") appendSystemNotice(data.payload?.message || "运行失败，请重试。", true);
      if (["action_decided", "plan_applied"].includes(name)) refreshWorkspaceSummary();
      setRunning(!["done", "error", "action_required", "action_decided", "plan_applied"].includes(name), labels[name]);
      if (["done", "error", "action_decided", "plan_applied"].includes(name)) {
        stopped = true;
        source.close();
        setRunning(false, labels[name]);
      }
    }));
    source.onerror = () => {
      if (stopped) return;
      source.close();
      window.setTimeout(() => watchEvents(cursor), 1200);
    };
  };

  if (composer) {
    input?.addEventListener("keydown", (event) => {
      // Enter 发送，Shift+Enter 保留换行；组合输入法确认时不拦截。
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        composer.requestSubmit();
      }
    });
    composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      const content = input.value.trim();
      if (!sessionId || !content) return;
      setRunning(true, "提交请求");
      const response = await fetch(`/api/v1/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, deep_mode: deepMode.checked })
      });
      if (!response.ok) {
        const error = await response.json();
        setRunning(false);
        window.alert(error.detail || "请求失败");
        return;
      }
      const accepted = await response.json();
      appendMessage("user", content);
      input.value = "";
      watchEvents(accepted.after_event_id || 0);
    });
  }

  document.getElementById("retry-session")?.addEventListener("click", async () => {
    setRunning(true, "恢复上次请求");
    const response = await fetch(`/api/v1/sessions/${sessionId}/retry`, { method: "POST" });
    if (!response.ok) {
      setRunning(false, "恢复失败");
      return;
    }
    const accepted = await response.json();
    watchEvents(accepted.after_event_id || 0);
  });

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
  }[char]));

  const renderActionCard = (action) => `
    <section class="action-card" data-action-id="${escapeHtml(action.id)}">
      <div class="action-card-copy">
        <div class="action-kicker"><i data-lucide="circle-alert"></i><span>待处理操作</span></div>
        <strong>${escapeHtml(action.title)}</strong>
        <p>${escapeHtml(action.description)}</p>
        ${action.payload?.plan ? `<div class="action-meta">计划：${escapeHtml(action.payload.plan.title || "未命名课程")} · ${action.payload.plan.duration_days} 天 · 版本 ${action.payload.plan.version} · ${action.payload.plan.stages?.length || 0} 个阶段</div><div class="action-outline">${(action.payload.plan.stages || []).slice(0, 3).map((stage) => `<span>${escapeHtml(stage.title)}${stage.lessons?.length ? ` · ${escapeHtml(stage.lessons[0].title)}` : ""}</span>`).join("")}</div>` : ""}
        ${action.available_decisions?.includes("suggest") ? `<div class="action-suggestion" hidden>
          <div class="suggestion-chips">
            <button type="button" class="chip suggestion-chip" data-suggestion="缩短学习周期，减少每天任务数量。">缩短周期</button>
            <button type="button" class="chip suggestion-chip" data-suggestion="增加到期复习和错题巩固。">增加复习</button>
            <button type="button" class="chip suggestion-chip" data-suggestion="调整学习时间，优先安排短任务。">调整时间</button>
          </div>
          <textarea class="suggestion-input" rows="2" maxlength="2000" placeholder="描述希望如何修改计划"></textarea>
          <button type="button" class="button primary action-submit-suggestion">生成新提案</button>
        </div>` : ""}
      </div>
      <div class="action-actions">
        ${action.available_decisions?.includes("cancel") ? '<button class="button secondary action-decision" data-decision="cancel">取消</button>' : ""}
        ${action.available_decisions?.includes("reject") ? '<button class="button secondary action-decision" data-decision="reject">拒绝</button>' : ""}
        ${action.available_decisions?.includes("suggest") ? '<button class="button secondary action-decision" data-decision="suggest">修改建议</button>' : ""}
        ${action.available_decisions?.includes("next") ? '<button class="button secondary action-decision" data-decision="next">继续下一步</button>' : ""}
        ${action.available_decisions?.includes("execute") ? '<button class="button primary action-decision" data-decision="execute">执行</button>' : ""}
      </div>
    </section>`;

  const refreshPlan = async () => {
    if (!sessionId) return;
    const response = await fetch(`/api/v1/plans/${sessionId}`);
    if (!response.ok) return;
    const data = await response.json();
    const board = document.getElementById("plan-board");
    if (!board) return;
    const progress = data.progress || {};
    const strong = board.querySelector(".plan-board-head strong");
    const pill = board.querySelector(".progress-pill");
    const fill = board.querySelector(".progress-track span");
    if (strong) strong.textContent = `${progress.completed || 0}/${progress.total || 0} 项完成`;
    if (pill) pill.textContent = `${progress.percent || 0}%`;
    if (fill) fill.style.width = `${progress.percent || 0}%`;
  };

  const refreshWorkspaceSummary = async () => {
    if (!sessionId) return;
    const [stateResponse, planResponse, actionsResponse] = await Promise.all([
      fetch(`/api/v1/sessions/${sessionId}/state`),
      fetch(`/api/v1/plans/${sessionId}`),
      fetch(`/api/v1/actions/pending?session_id=${encodeURIComponent(sessionId)}`)
    ]);
    if (!stateResponse.ok || !planResponse.ok) return;
    const state = await stateResponse.json();
    const overview = await planResponse.json();
    const progress = overview.progress || {};
    const learning = state.learning || {};
    setAgentRole(state.latest_run?.agent_role || "interactive");
    const concepts = learning.concepts || [];
    const dueReviews = learning.due_reviews || [];
    const progressPercent = document.getElementById("context-progress-percent");
    const progressFill = document.getElementById("context-progress-fill");
    if (progressPercent) progressPercent.textContent = `${progress.percent || 0}%`;
    if (progressFill) progressFill.style.width = `${progress.percent || 0}%`;
    const conceptCount = document.getElementById("context-concept-count");
    const dueCount = document.getElementById("context-due-count");
    const pendingCount = document.getElementById("context-pending-count");
    if (conceptCount) conceptCount.textContent = String(Array.isArray(concepts) ? concepts.length : Object.keys(concepts).length);
    if (dueCount) dueCount.textContent = String(dueReviews.length);
    if (pendingCount && actionsResponse.ok) pendingCount.textContent = String((await actionsResponse.json()).actions?.length || 0);
    const stage = document.getElementById("runtime-stage");
    if (stage && state.session?.status === "completed") stage.textContent = "completed";

    const plan = state.today_plan?.payload || state.today_plan;
    const count = document.getElementById("today-plan-count");
    const list = document.getElementById("today-plan-list");
    const empty = document.getElementById("today-plan-empty");
    if (!plan) {
      if (count) count.textContent = "尚未生成";
      if (list) list.remove();
      if (!empty) {
        const placeholder = document.createElement("div");
        placeholder.className = "empty-small";
        placeholder.id = "today-plan-empty";
        placeholder.textContent = "批准课程计划后生成今日任务。";
        count?.closest(".panel-heading")?.after(placeholder);
      }
      return;
    }
    if (count) count.textContent = `${plan.tasks?.length || 0} 个任务`;
    empty?.remove();
    let taskList = list;
    if (!taskList) {
      taskList = document.createElement("ul");
      taskList.className = "compact-task-list";
      taskList.id = "today-plan-list";
      count?.closest(".panel-heading")?.after(taskList);
    }
    taskList.innerHTML = (plan.tasks || []).slice(0, 4).map((task) =>
      `<li class="${task.completed ? "complete" : ""}"><i data-lucide="${task.completed ? "check-circle-2" : "circle"}"></i><span>${escapeHtml(task.title)}</span></li>`
    ).join("");
    icons();
  };

  const refreshPlanTable = async () => {
    await refreshPlan();
    const response = await fetch(`/api/v1/plans/${sessionId}`);
    if (!response.ok) return;
    const data = await response.json();
    const rows = data.rows || [];
    rows.forEach((item) => {
      const row = [...document.querySelectorAll("tr")].find((candidate) =>
        candidate.querySelector(`[data-stage-id="${CSS.escape(item.stage_id)}"]`)
      );
      if (!row) return;
      const status = row.querySelector(".status-chip");
      if (status) {
        status.textContent = item.status;
        status.className = `status-chip ${item.completed ? "status-complete" : item.status === "进行中" ? "status-active" : "status-pending"}`;
      }
      if (item.completed) {
        const actionCell = row.lastElementChild;
        if (actionCell) actionCell.innerHTML = '<span class="table-check"><i data-lucide="check-circle-2"></i></span>';
        row.classList.add("is-complete");
      }
    });
    icons();
  };

  const taskModal = document.getElementById("task-result-modal");
  const taskResultForm = document.getElementById("task-result-form");
  const taskResultId = document.getElementById("task-result-id");
  const taskResultScore = document.getElementById("task-result-score");
  const taskResultScoreValue = document.getElementById("task-result-score-value");
  const taskResultFeedback = document.getElementById("task-result-feedback");
  let activeTaskCard = null;

  const setTaskFeedback = (message, error = false) => {
    if (!taskResultFeedback) return;
    taskResultFeedback.textContent = message;
    taskResultFeedback.style.color = error ? "var(--coral)" : "var(--green)";
  };

  const closeTaskModal = () => {
    if (taskModal) taskModal.hidden = true;
    activeTaskCard = null;
    setTaskFeedback("");
  };

  const updateTaskCard = (task) => {
    const card = document.querySelector(`[data-task-id="${CSS.escape(task.id)}"]`);
    if (!card) return;
    card.dataset.taskStatus = task.status || (task.completed ? "completed" : "pending");
    card.classList.toggle("is-complete", Boolean(task.completed));
    const status = card.querySelector(".task-status");
    if (status) {
      status.textContent = task.completed ? "已完成" : task.status === "in_progress" ? "进行中" : "待开始";
      status.className = `status-chip task-status ${task.completed ? "status-complete" : task.status === "in_progress" ? "status-active" : "status-pending"}`;
    }
    const start = card.querySelector(".daily-task-start");
    if (start) start.disabled = Boolean(task.completed) || task.status === "in_progress";
    const resultButton = card.querySelector(".daily-task-result");
    if (resultButton) resultButton.lastChild.textContent = task.completed ? "更新记录" : "记录结果";
    let summary = card.querySelector(".task-result-summary");
    if (task.score !== null && task.score !== undefined) {
      if (!summary) {
        summary = document.createElement("div");
        summary.className = "task-result-summary";
        card.querySelector(".daily-task-main")?.appendChild(summary);
      }
      summary.textContent = `上次得分 ${Math.round(task.score * 100)}%${task.notes ? ` · ${task.notes}` : ""}`;
    }
  };

  const openTaskModal = (card) => {
    if (!taskModal || !taskResultForm) return;
    activeTaskCard = card;
    taskModal.hidden = false;
    taskResultId.value = card.dataset.taskId || "";
    taskResultForm.querySelector("#task-result-answer").value = "";
    taskResultForm.querySelector("#task-result-notes").value = "";
    taskResultForm.querySelector("#task-result-error").value = "";
    taskResultScore.value = "0.8";
    taskResultScoreValue.textContent = "80%";
    taskResultForm.querySelector("#task-result-answer")?.focus();
    icons();
  };

  taskResultScore?.addEventListener("input", () => {
    if (taskResultScoreValue) taskResultScoreValue.textContent = `${Math.round(Number(taskResultScore.value) * 100)}%`;
  });
  taskResultForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const taskId = taskResultId.value;
    if (!sessionId || !taskId) return;
    const submit = taskResultForm.querySelector("button[type=submit]");
    if (submit) submit.disabled = true;
    setTaskFeedback("正在保存学习记录…");
    const response = await fetch(`/api/v1/plans/${sessionId}/tasks/${encodeURIComponent(taskId)}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        score: Number(taskResultScore.value),
        answer: taskResultForm.querySelector("#task-result-answer").value.trim(),
        notes: taskResultForm.querySelector("#task-result-notes").value.trim(),
        error_category: taskResultForm.querySelector("#task-result-error").value || null,
        completed: true
      })
    });
    if (!response.ok) {
      let detail = "学习记录保存失败，请重试。";
      try { detail = (await response.json()).detail || detail; } catch (_) { /* ignore */ }
      setTaskFeedback(detail, true);
      if (submit) submit.disabled = false;
      return;
    }
    const result = await response.json();
    const task = result.plan?.tasks?.find((item) => item.id === taskId);
    if (task) updateTaskCard(task);
    closeTaskModal();
    await refreshWorkspaceSummary();
    if (submit) submit.disabled = false;
    icons();
  });

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.matches(".modal-close")) {
      closeTaskModal();
      return;
    }
    const card = target.closest(".daily-task-card");
    if (!card) return;
    if (target.matches(".daily-task-result")) {
      openTaskModal(card);
      return;
    }
    if (target.matches(".daily-task-start")) {
      target.disabled = true;
      const response = await fetch(`/api/v1/plans/${sessionId}/tasks/${encodeURIComponent(card.dataset.taskId)}/start`, { method: "POST" });
      if (!response.ok) {
        target.disabled = false;
        return;
      }
      const plan = await response.json();
      const task = plan.tasks?.find((item) => item.id === card.dataset.taskId);
      if (task) updateTaskCard(task);
    }
  });
  taskModal?.addEventListener("click", (event) => {
    if (event.target === taskModal) closeTaskModal();
  });

  const reviewModal = document.getElementById("review-result-modal");
  const reviewResultForm = document.getElementById("review-result-form");
  const reviewResultConcept = document.getElementById("review-result-concept");
  const reviewResultScore = document.getElementById("review-result-score");
  const reviewResultScoreValue = document.getElementById("review-result-score-value");
  const reviewResultFeedback = document.getElementById("review-result-feedback");
  let activeReviewRow = null;

  const setReviewFeedback = (message, error = false) => {
    if (!reviewResultFeedback) return;
    reviewResultFeedback.textContent = message;
    reviewResultFeedback.style.color = error ? "var(--coral)" : "var(--green)";
  };
  const closeReviewModal = () => {
    if (reviewModal) reviewModal.hidden = true;
    activeReviewRow = null;
    setReviewFeedback("");
  };
  reviewResultScore?.addEventListener("input", () => {
    if (reviewResultScoreValue) reviewResultScoreValue.textContent = `${Math.round(Number(reviewResultScore.value) * 100)}%`;
  });
  reviewResultForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const conceptId = reviewResultConcept.value;
    if (!sessionId || !conceptId) return;
    const submit = reviewResultForm.querySelector("button[type=submit]");
    if (submit) submit.disabled = true;
    setReviewFeedback("正在保存复习记录…");
    const response = await fetch(`/api/v1/reviews/${sessionId}/items/${encodeURIComponent(conceptId)}/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        score: Number(reviewResultScore.value),
        answer: reviewResultForm.querySelector("#review-result-answer").value.trim(),
        notes: reviewResultForm.querySelector("#review-result-notes").value.trim(),
        error_category: reviewResultForm.querySelector("#review-result-error").value || null,
        completed: true
      })
    });
    if (!response.ok) {
      let detail = "复习记录保存失败，请重试。";
      try { detail = (await response.json()).detail || detail; } catch (_) { /* ignore */ }
      setReviewFeedback(detail, true);
      if (submit) submit.disabled = false;
      return;
    }
    activeReviewRow?.remove();
    closeReviewModal();
    if (submit) submit.disabled = false;
    icons();
  });
  document.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.matches(".review-modal-close")) {
      closeReviewModal();
      return;
    }
    if (!target.matches(".review-result-action") || !reviewModal) return;
    activeReviewRow = target.closest(".review-row");
    reviewResultConcept.value = target.dataset.conceptId || "";
    reviewResultForm.querySelector("#review-result-answer").value = "";
    reviewResultForm.querySelector("#review-result-notes").value = "";
    reviewResultForm.querySelector("#review-result-error").value = "";
    reviewResultScore.value = "0.8";
    reviewResultScoreValue.textContent = "80%";
    reviewModal.hidden = false;
    reviewResultForm.querySelector("#review-result-answer")?.focus();
    icons();
  });
  reviewModal?.addEventListener("click", (event) => {
    if (event.target === reviewModal) closeReviewModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (taskModal && !taskModal.hidden) closeTaskModal();
    if (reviewModal && !reviewModal.hidden) closeReviewModal();
  });

  const showActionError = (card, message) => {
    let error = card.querySelector(".action-error");
    if (!error) {
      error = document.createElement("p");
      error.className = "action-error";
      card.querySelector(".action-card-copy").appendChild(error);
    }
    error.textContent = message;
  };

  document.addEventListener("click", async (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    const chip = target.closest(".suggestion-chip");
    if (chip) {
      const input = chip.closest(".action-suggestion")?.querySelector(".suggestion-input");
      if (input) input.value = chip.dataset.suggestion || "";
      return;
    }
    const card = target.closest(".action-card");
    if (!card) return;
    const suggestionBox = card.querySelector(".action-suggestion");
    if (target.matches("[data-decision='suggest']")) {
      suggestionBox.hidden = false;
      suggestionBox.querySelector(".suggestion-input")?.focus();
      return;
    }
    if (target.matches(".action-submit-suggestion")) {
      const message = suggestionBox.querySelector(".suggestion-input")?.value.trim();
      if (!message) return showActionError(card, "请先填写修改建议。");
      await decideAction(card, "suggest", message);
      return;
    }
    if (target.matches(".action-decision")) {
      await decideAction(card, target.dataset.decision, null);
    }
  });

  const decideAction = async (card, decision, message) => {
    const buttons = [...card.querySelectorAll("button")];
    buttons.forEach((button) => { button.disabled = true; });
    const response = await fetch(`/api/v1/actions/${card.dataset.actionId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, message })
    });
    if (!response.ok) {
      let detail = "操作失败，请重试。";
      try { detail = (await response.json()).detail || detail; } catch (_) { /* ignore */ }
      showActionError(card, detail);
      buttons.forEach((button) => { button.disabled = false; });
      return;
    }
    const result = await response.json();
    if (result.new_action?.id) {
      const actionResponse = await fetch(`/api/v1/actions/${result.new_action.id}`);
      if (actionResponse.ok) card.outerHTML = renderActionCard(await actionResponse.json());
    } else {
      card.outerHTML = `<div class="action-result">${decision === "execute" ? "计划已生效，可以开始今日学习。" : decision === "reject" ? "计划未生效，可以继续调整目标。" : "流程已取消。"}</div>`;
    }
    if (result.today_plan || decision === "execute") await refreshPlan();
    await refreshWorkspaceSummary();
    icons();
    setRunning(false, "本地运行");
  };

  document.querySelectorAll(".plan-complete-action").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!sessionId) return;
      button.disabled = true;
      const response = await fetch(
        `/api/v1/plans/${sessionId}/tasks/${encodeURIComponent(button.dataset.stageId)}/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ completed: true })
        }
      );
      if (response.ok) await refreshPlanTable();
      else button.disabled = false;
    });
  });

  const sessionSearch = document.getElementById("session-search");
  sessionSearch?.addEventListener("input", () => {
    const query = sessionSearch.value.trim().toLowerCase();
    document.querySelectorAll(".session-row").forEach((item) => {
      item.hidden = query && !item.dataset.sessionTitle.toLowerCase().includes(query);
    });
  });

  document.querySelectorAll(".session-menu-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = button.nextElementSibling;
      document.querySelectorAll(".session-menu").forEach((item) => {
        if (item !== menu) item.hidden = true;
      });
      menu.hidden = !menu.hidden;
    });
  });
  document.querySelectorAll("[data-session-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest(".session-row");
      if (button.dataset.sessionAction === "rename") {
        const title = window.prompt("输入新的会话标题", row.dataset.sessionTitle);
        if (!title?.trim()) return;
        const response = await fetch(`/api/v1/sessions/${row.dataset.sessionId}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: title.trim() })
        });
        if (response.ok) {
          const updated = await response.json();
          row.dataset.sessionTitle = updated.title;
          row.querySelector(".session-info strong").textContent = updated.title;
          row.querySelector(".session-symbol").textContent = [...updated.title][0] || "新";
          row.querySelector(".session-menu").hidden = true;
        }
        return;
      }
      if (button.dataset.sessionAction === "pin") {
        const pinned = row.dataset.pinned !== "true";
        const response = await fetch(`/api/v1/sessions/${row.dataset.sessionId}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pinned })
        });
        if (response.ok) {
          row.dataset.pinned = String(pinned);
          button.textContent = pinned ? "取消置顶" : "置顶";
          row.classList.toggle("is-pinned", pinned);
        }
        return;
      }
      if (!window.confirm(`删除会话“${row.dataset.sessionTitle}”？该操作不可撤销。`)) return;
      const response = await fetch(`/api/v1/sessions/${row.dataset.sessionId}`, { method: "DELETE" });
      if (response.ok) window.location.assign("/");
    });
  });

  // Notifications 页面打开时主动同步 SMTP 状态，避免把本地 outbox 误报为真实发送。
  const smtpStatus = document.querySelector(".smtp-status span");
  if (smtpStatus && sessionId) {
    fetch(`/api/v1/notifications/settings/${sessionId}`).then((response) => response.ok ? response.json() : null)
      .then((setting) => {
        if (!setting) return;
        smtpStatus.textContent = setting.verified_at
          ? "SMTP 已验证；密码仅由服务器环境变量提供。"
          : "SMTP 尚未验证；保存邮箱后可发送测试邮件。";
      }).catch(() => {});
  }
  document.addEventListener("click", () => document.querySelectorAll(".session-menu").forEach((menu) => { menu.hidden = true; }));

  const notificationForm = document.getElementById("notification-form");
  const notificationFeedback = document.getElementById("notification-feedback");
  const setNotificationFeedback = (message, error = false) => {
    if (!notificationFeedback) return;
    notificationFeedback.textContent = message;
    notificationFeedback.style.color = error ? "var(--coral)" : "var(--green)";
  };
  const notificationPayload = () => ({
    email: document.getElementById("notification-email").value.trim(),
    enabled: document.getElementById("notification-enabled").checked,
    timezone: document.getElementById("notification-timezone").value.trim(),
    morning_time: document.getElementById("notification-morning").value,
    evening_time: document.getElementById("notification-evening").value
  });
  const saveNotificationSettings = async () => fetch(`/api/v1/notifications/settings/${sessionId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(notificationPayload())
  });
  notificationForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await saveNotificationSettings();
    if (!response.ok) {
      setNotificationFeedback("设置保存失败，请检查邮箱和时区。", true);
      return;
    }
    const result = await response.json();
    setNotificationFeedback(result.message || "提醒设置已保存。", Boolean(result.activation_required));
  });
  document.getElementById("notification-test")?.addEventListener("click", async () => {
    const email = document.getElementById("notification-email").value.trim();
    if (!email) {
      setNotificationFeedback("请先填写收件邮箱。", true);
      return;
    }
    setNotificationFeedback("正在保存设置并发送测试邮件…");
    const saved = await saveNotificationSettings();
    if (!saved.ok) {
      let detail = "设置保存失败，请检查邮箱和时区。";
      try { detail = (await saved.json()).detail || detail; } catch (_) { /* ignore */ }
      setNotificationFeedback(detail, true);
      return;
    }
    const response = await fetch(`/api/v1/notifications/test/${sessionId}`, { method: "POST" });
    if (response.ok) {
      const result = await response.json();
      if (result.delivery_mode === "smtp" && document.getElementById("notification-enabled").checked) {
        await saveNotificationSettings();
      }
      setNotificationFeedback(result.delivery_mode === "smtp" ? "测试邮件已发送，SMTP 验证成功；勾选的定时提醒已同步启用。" : "测试邮件已写入本地 outbox，尚未验证真实 SMTP。", result.delivery_mode !== "smtp");
      return;
    }
    let detail = "测试邮件发送失败，请检查 SMTP 配置。";
    try { detail = (await response.json()).detail || detail; } catch (_) { /* ignore */ }
    setNotificationFeedback(detail, true);
  });

  const messages = document.getElementById("messages");
  if (messages) messages.scrollTop = messages.scrollHeight;
  if (messages && sessionId) refreshWorkspaceSummary();
})();
