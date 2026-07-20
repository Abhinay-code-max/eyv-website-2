import React from "react";

export default function ErrorFallback({ resetError }) {
  return (
    <div className="min-h-screen bg-[#FDFBF7] flex flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold text-gray-800">Something went wrong</h1>
      <p className="text-gray-600 max-w-md">
        We've hit an unexpected error and have been notified. Try refreshing the page.
      </p>
      <button
        onClick={resetError}
        className="px-5 py-2 rounded-full bg-[#C47245] text-white hover:opacity-90 transition-opacity"
      >
        Try again
      </button>
    </div>
  );
}
