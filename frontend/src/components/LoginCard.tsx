type LoginCardProps = {
  onLogin: (email: string, password: string) => Promise<void>;
  error?: string;
};

export function LoginCard({ onLogin, error }: LoginCardProps) {
  return (
    <div className="animate-fade-in" style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", width: "100vw", backgroundColor: "var(--bg-base)" }}>
      <div className="card glass-panel" style={{ width: "100%", maxWidth: "440px", padding: "2.5rem" }}>
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <p className="text-brand text-sm" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600, marginBottom: "0.5rem" }}>MemoryOS Cloud</p>
          <h2 className="text-3xl mb-2">Sign into workspace</h2>
          <p className="text-secondary text-sm mt-2">
            Enterprise memory for chatbots, copilots, and AI agents. The dashboard signs in with your workspace email and password, not an API key.
          </p>
        </div>

        <form
          className="space-y-6"
          onSubmit={async (event) => {
            event.preventDefault();
            const formData = new FormData(event.currentTarget);
            await onLogin(String(formData.get("email") || ""), String(formData.get("password") || ""));
          }}
        >
          <div>
            <label className="label-base">Email</label>
            <input className="input-base" name="email" type="email" placeholder="founder@company.com" required />
          </div>
          <div>
            <label className="label-base">Password</label>
            <input className="input-base" name="password" type="password" placeholder="********" required />
          </div>

          {error ? <p style={{ color: "var(--danger)", fontSize: "0.875rem", marginTop: "0.5rem" }}>{error}</p> : null}

          <button className="btn btn-primary w-full" type="submit" style={{ marginTop: "1rem" }}>
            Sign in
          </button>
        </form>
      </div>
    </div>
  );
}
