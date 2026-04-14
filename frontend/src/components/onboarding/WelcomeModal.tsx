"use client";

import { useState } from "react";
import { Upload, FileText, MessageSquare, X } from "lucide-react";

const STORAGE_KEY = "onboarding_dismissed";

function getInitialVisible(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(STORAGE_KEY) !== "true";
}

interface Step {
  icon: React.ReactNode;
  title: string;
  description: string;
}

const steps: Step[] = [
  {
    icon: <Upload size={22} />,
    title: "Tải lên dữ liệu",
    description:
      "Nhấn nút Data ở góc trên → tải lên file CSV. Có thể tải nhiều bảng dữ liệu khác nhau.",
  },
  {
    icon: <FileText size={22} />,
    title: "Thêm Business Context",
    description:
      "Sau khi upload, thêm mô tả ngữ cảnh kinh doanh cho từng bảng (ví dụ: 'Dữ liệu bán hàng Q1/2025'). Điều này giúp agent hiểu rõ data của bạn.",
  },
  {
    icon: <MessageSquare size={22} />,
    title: "Đặt câu hỏi",
    description:
      "Hỏi bằng tiếng Việt hoặc English. Agent có thể: truy vấn SQL, vẽ biểu đồ, phân tích xu hướng, hoặc viết báo cáo chi tiết.",
  },
];

export function WelcomeModal() {
  const [visible, setVisible] = useState(getInitialVisible);
  const [dontShowAgain, setDontShowAgain] = useState(false);

  const handleDismiss = () => {
    if (dontShowAgain) {
      localStorage.setItem(STORAGE_KEY, "true");
    }
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-[fadeIn_150ms_ease-out]">
      <div className="relative w-full max-w-md mx-4 bg-white dark:bg-[#1e1e1e] rounded-2xl shadow-2xl border border-[#e5e2db] dark:border-[#333] overflow-hidden">
        {/* Close button */}
        <button
          onClick={handleDismiss}
          className="absolute top-3 right-3 p-1.5 rounded-lg hover:bg-[#f0ede6] dark:hover:bg-[#2a2a2a] text-[#8a8a8a] hover:text-[#3a3a3a] dark:text-[#777] dark:hover:text-[#ddd] transition-colors"
          aria-label="Close"
        >
          <X size={16} />
        </button>

        {/* Header */}
        <div className="px-6 pt-6 pb-2">
          <h2 className="text-lg font-semibold text-[#2f2f2f] dark:text-[#f1f1f1]">
            Chào mừng đến DA Agent Lab
          </h2>
          <p className="text-sm text-[#6f6f6f] dark:text-[#ababab] mt-1 leading-relaxed">
            Trợ lý phân tích dữ liệu thông minh. Bắt đầu trong 3 bước đơn giản:
          </p>
        </div>

        {/* Steps */}
        <div className="px-6 py-4 space-y-4">
          {steps.map((step, i) => (
            <div key={i} className="flex gap-3.5">
              <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-[#f0ede6] dark:bg-[#2a2a2a] flex items-center justify-center text-[#4a4a4a] dark:text-[#c7c7c7]">
                {step.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-medium text-[#8a8a8a] dark:text-[#777] uppercase tracking-wider">
                    Bước {i + 1}
                  </span>
                </div>
                <p className="text-sm font-medium text-[#2f2f2f] dark:text-[#e8e8e8] mt-0.5">
                  {step.title}
                </p>
                <p className="text-[13px] text-[#6a6a6a] dark:text-[#999] mt-0.5 leading-relaxed">
                  {step.description}
                </p>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#eae7df] dark:border-[#2d2d2d] flex items-center justify-between">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={dontShowAgain}
              onChange={(e) => setDontShowAgain(e.target.checked)}
              className="w-3.5 h-3.5 rounded border-[#c5c0b6] dark:border-[#555] text-[#4a4a4a] dark:text-[#bbb] focus:ring-0"
            />
            <span className="text-[12px] text-[#7a7a7a] dark:text-[#888]">
              Không hiển thị lại
            </span>
          </label>
          <button
            onClick={handleDismiss}
            className="px-4 py-2 text-sm font-medium rounded-xl bg-[#2f2f2f] hover:bg-[#3a3a3a] dark:bg-[#e9e9e9] dark:hover:bg-[#dcdcdc] text-white dark:text-[#171717] transition-colors"
          >
            Bắt đầu
          </button>
        </div>
      </div>
    </div>
  );
}
