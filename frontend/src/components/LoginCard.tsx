type LoginCardProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error?: string;
};

export function LoginCard({ onLogin, error }: LoginCardProps) {
  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="login-copy">
          <p className="eyebrow">MemoryOS Cloud</p>
          <h1>Enterprise memory for chatbots, copilots, and AI agents.</h1>
          <p>
            Fast writes, token-light retrieval, evolving knowledge graphs, and memory that makes
            agents better over time.
          </p>
        </div>

        <form
          className="login-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const formData = new FormData(event.currentTarget);
            await onLogin(String(formData.get("email") || ""), String(formData.get("password") || ""));
          }}
        >
          <label>
            Email
            <input name="email" type="email" placeholder="founder@company.com" required />
          </label>
          <label>
            Password
            <input name="password" type="password" placeholder="••••••••" required />
          </label>
          {error ? <p className="error-text">{error}</p> : null}
          <button className="primary-button" type="submit">
            Sign in
          </button>
        </form>
      </section>
    </main>
  );
}
