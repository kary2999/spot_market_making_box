/**
 * 登录页前端逻辑
 * - 客户端输入验证
 * - 调用 POST /api/auth/login
 * - 错误提示 / 加载状态
 * - 登录成功后将 token 存入 localStorage 并跳转首页
 */

(function () {
  "use strict";

  const form        = document.getElementById("loginForm");
  const usernameEl  = document.getElementById("username");
  const passwordEl  = document.getElementById("password");
  const submitBtn   = document.getElementById("submitBtn");
  const spinner     = document.getElementById("spinner");
  const btnText     = document.getElementById("btnText");
  const globalError = document.getElementById("globalError");
  const usernameErr = document.getElementById("usernameError");
  const passwordErr = document.getElementById("passwordError");

  /* ── 已登录则直接跳首页 ── */
  if (localStorage.getItem("access_token")) {
    window.location.replace("/");
    return;
  }

  /* ── 工具函数 ── */
  function setLoading(loading) {
    submitBtn.disabled  = loading;
    spinner.style.display = loading ? "block" : "none";
    btnText.textContent = loading ? "登录中..." : "登录";
  }

  function showGlobalError(msg, locked) {
    globalError.textContent = msg;
    globalError.className   = "alert" + (locked ? " locked" : "");
    globalError.style.display = "block";
  }

  function clearErrors() {
    globalError.style.display = "none";
    usernameErr.textContent   = "";
    passwordErr.textContent   = "";
    usernameEl.classList.remove("invalid");
    passwordEl.classList.remove("invalid");
  }

  /* ── 客户端校验 ── */
  function validate() {
    let ok = true;
    const username = usernameEl.value.trim();
    const password = passwordEl.value;

    if (!username) {
      usernameErr.textContent = "请输入用户名";
      usernameEl.classList.add("invalid");
      ok = false;
    }

    if (!password) {
      passwordErr.textContent = "请输入密码";
      passwordEl.classList.add("invalid");
      ok = false;
    } else if (password.length < 6) {
      passwordErr.textContent = "密码长度不能少于 6 位";
      passwordEl.classList.add("invalid");
      ok = false;
    }

    return ok;
  }

  /* ── token 刷新（可在其他页面复用） ── */
  async function refreshAccessToken() {
    const refresh_token = localStorage.getItem("refresh_token");
    if (!refresh_token) return false;

    try {
      const res = await fetch("/api/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      localStorage.setItem("access_token", data.access_token);
      return true;
    } catch (_) {
      return false;
    }
  }

  /* ── 表单提交 ── */
  form.addEventListener("submit", async function (e) {
    e.preventDefault();
    clearErrors();

    if (!validate()) return;

    setLoading(true);

    const username = usernameEl.value.trim();
    const password = passwordEl.value;

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (res.ok) {
        localStorage.setItem("access_token",  data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        localStorage.setItem("username",      data.username);
        window.location.replace("/");
        return;
      }

      /* 账户锁定 (423) */
      if (res.status === 423) {
        showGlobalError(data.error, true);
        return;
      }

      /* 其他认证失败 */
      showGlobalError(data.error || "登录失败，请稍后重试", false);

    } catch (_) {
      showGlobalError("网络异常，请检查连接后重试", false);
    } finally {
      setLoading(false);
    }
  });

  /* 实时清除字段错误 */
  usernameEl.addEventListener("input", function () {
    usernameErr.textContent = "";
    usernameEl.classList.remove("invalid");
  });
  passwordEl.addEventListener("input", function () {
    passwordErr.textContent = "";
    passwordEl.classList.remove("invalid");
  });

  /* 导出供其他模块使用 */
  window.AuthUtils = { refreshAccessToken };
})();
