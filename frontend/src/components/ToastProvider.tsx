import { createContext, useContext, useState, type ReactNode } from "react";

type ToastType = "success" | "error" | "info";

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string, type: ToastType } | null>(null);

  const showToast = (message: string, type: ToastType = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  const getBackgroundColor = (type: ToastType) => {
    if (type === "success") return "rgba(16, 185, 129, 0.9)";
    if (type === "error") return "rgba(239, 68, 68, 0.9)";
    return "var(--bg-surface-elevated)";
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && (
        <div 
          style={{
            position: "fixed",
            bottom: "24px",
            right: "24px",
            padding: "1rem 1.5rem",
            backgroundColor: getBackgroundColor(toast.type),
            color: "white",
            borderRadius: "var(--radius-sm)",
            boxShadow: "var(--shadow-md)",
            zIndex: 9999,
            animation: "fadeIn 0.3s ease",
            border: "1px solid var(--border-strong)"
          }}
        >
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  );
}

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used within ToastProvider");
  return context;
};
