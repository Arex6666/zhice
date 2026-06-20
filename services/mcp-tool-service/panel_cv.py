"""purged + embargoed 时序交叉验证（纯函数，López de Prado《Advances in Financial ML》）。

按时间顺序把样本切成连续测试折；每折训练集**剔除**与测试期标签窗 [t, t+horizon] 重叠者
及 embargo 缓冲区，杜绝"用未来标签训练"的泄漏。这是单因子设计网格多路径与 ML 合成 CV 的基底。
"""


def purged_split(n, n_splits=5, embargo=5, horizon=5):
    """返回 [(train_idx, test_idx), ...]，按时间分 n_splits 连续测试折，训练集做 purge+embargo。

    样本不足（n < n_splits 或每折<1）返回 []。
    """
    n = int(n)
    if n < n_splits or n_splits < 1:
        return []
    fold = n // n_splits
    if fold < 1:
        return []
    folds = []
    for k in range(n_splits):
        start = k * fold
        end = (k + 1) * fold if k < n_splits - 1 else n   # 最后一折吃尾
        test = list(range(start, end))
        lo = start - embargo
        hi = (end - 1) + horizon                          # 测试期标签窗右界
        train = [i for i in range(n) if i not in range(start, end) and not (lo <= i <= hi)]
        folds.append((train, test))
    return folds
