# threshold_optimizer.py
import pandas as pd

class ThresholdOptimizer:
    @staticmethod
    def get_adaptive_threshold(df_intraday, base_level=35, percentile=20):
        """
        基于标的历史RSI分布计算自适应阈值
        :param df_intraday: 15min 原始数据（含RSI列）
        :param base_level: 基础保底阈值，防止在极度弱势行情中阈值过高
        :param percentile: 取分布的低位百分比
        """
        if 'RSI' not in df_intraday.columns or df_intraday['RSI'].isnull().all():
            return base_level
        
        # 计算历史RSI的百分位数值
        adaptive_val = df_intraday['RSI'].quantile(percentile / 100)
        
        # 逻辑约束：自适应阈值不应高于 50（中轴），也不应低于 25（极端情况）
        final_threshold = max(25, min(50, adaptive_val))
        return round(final_threshold, 2)