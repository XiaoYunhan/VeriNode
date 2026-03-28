import type { ButtonHTMLAttributes } from "react";
import { cn } from "../../lib/utils";

type ButtonVariant = "default" | "secondary" | "ghost";

const variantClasses: Record<ButtonVariant, string> = {
  default:
    "bg-[#1f7c6f] text-white shadow-[0_14px_32px_rgba(31,124,111,0.18)] hover:bg-[#17695f]",
  secondary: "bg-[#e4efe9] text-[#174e48] hover:bg-[#d8e6df]",
  ghost: "bg-[#f0ebe2] text-[#34373c] hover:bg-[#e6dfd4]",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({
  className,
  type = "button",
  variant = "secondary",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2b7367]/40",
        "disabled:cursor-not-allowed disabled:opacity-55",
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  );
}
