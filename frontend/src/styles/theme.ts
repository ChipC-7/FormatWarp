// Naive UI 主题配置：色值从旧版 utils.py 的 COLORS_DARK / COLORS_LIGHT 平移
import type { GlobalTheme, GlobalThemeOverrides } from "naive-ui";
import { darkTheme, lightTheme } from "naive-ui";

// 暗色（默认）—— 与旧版 COLORS_DARK 对齐
export const darkOverrides: GlobalThemeOverrides = {
  common: {
    bodyColor: "#1a1a2e",
    cardColor: "#16213e",
    modalColor: "#16213e",
    popoverColor: "#16213e",
    inputColor: "#1a1a2e",
    borderColor: "#0f3460",
    dividerColor: "#0f3460",
    hoverColor: "#1e2a4a",
    primaryColor: "#e94560",
    primaryColorHover: "#ff6b81",
    primaryColorPressed: "#c0392b",
    primaryColorSuppl: "#ff6b81",
    infoColor: "#2980b9",
    successColor: "#00d9ff",
    successColorHover: "#00b8d4",
    warningColor: "#f9a826",
    errorColor: "#e94560",
    errorColorHover: "#ff4d4f",
    textColorBase: "#eaeaea",
    textColor1: "#eaeaea",
    textColor2: "#c8c8c8",
    textColor3: "#a0a0a0",
    textColorDisabled: "#666666",
    borderRadius: "8px",
    fontFamily: '"Noto Sans CJK SC","Source Han Sans CN","Microsoft YaHei",sans-serif',
  },
  Layout: {
    color: "#1a1a2e",
    siderColor: "#1a1a2e",
  },
  Menu: {
    itemTextColor: "#eaeaea",
    itemTextColorHover: "#eaeaea",
    itemTextColorActive: "#00d9ff",
    itemIconColor: "#a0a0a0",
    itemIconColorActive: "#00d9ff",
    itemColorActive: "#16213e",
    itemColorActiveHover: "#1e2a4a",
  },
  Card: {
    borderColor: "#0f3460",
  },
  Button: {
    colorPrimary: "#e94560",
    colorHoverPrimary: "#ff6b81",
  },
};

// 亮色 —— 与旧版 COLORS_LIGHT 对齐
export const lightOverrides: GlobalThemeOverrides = {
  common: {
    bodyColor: "#f4f6fb",
    cardColor: "#ffffff",
    modalColor: "#ffffff",
    popoverColor: "#ffffff",
    inputColor: "#ffffff",
    borderColor: "#c9d6ef",
    dividerColor: "#c9d6ef",
    hoverColor: "#eaf0fb",
    primaryColor: "#3a6ea5",
    primaryColorHover: "#2e5a88",
    primaryColorPressed: "#29527c",
    primaryColorSuppl: "#4a8bd6",
    infoColor: "#4a8bd6",
    successColor: "#0a85a0",
    successColorHover: "#086a83",
    warningColor: "#e08a00",
    errorColor: "#d9405d",
    errorColorHover: "#ff5a78",
    textColorBase: "#1a2440",
    textColor1: "#1a2440",
    textColor2: "#2c3a5c",
    textColor3: "#576485",
    textColorDisabled: "#8a96b5",
    borderRadius: "8px",
    fontFamily: '"Noto Sans CJK SC","Source Han Sans CN","Microsoft YaHei",sans-serif',
  },
  Layout: {
    color: "#f4f6fb",
    siderColor: "#f4f6fb",
  },
  Menu: {
    itemTextColor: "#1a2440",
    itemTextColorHover: "#1a2440",
    itemTextColorActive: "#0a85a0",
    itemIconColor: "#576485",
    itemIconColorActive: "#0a85a0",
    itemColorActive: "#ffffff",
    itemColorActiveHover: "#eaf0fb",
  },
  Card: {
    borderColor: "#c9d6ef",
  },
};

/** 返回当前主题的 Naive UI 内置主题对象 */
export function themeFor(mode: "dark" | "light"): GlobalTheme {
  return mode === "dark" ? darkTheme : lightTheme;
}

/** 返回当前主题的 themeOverrides */
export function overridesFor(mode: "dark" | "light"): GlobalThemeOverrides {
  return mode === "dark" ? darkOverrides : lightOverrides;
}
