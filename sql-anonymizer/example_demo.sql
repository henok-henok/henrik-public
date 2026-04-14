-- Supplier volume report
-- Author: Erik Johansson, Logistics dept
CREATE TABLE purchasing.Dim_Supplier (
    Supplier_SK INT NOT NULL,
    Supplier_Code NVARCHAR(50),
    Supplier_Name NVARCHAR(200),
    Supplier_Region NVARCHAR(50),
    Created_Date DATE DEFAULT GETDATE()
);
GO

EXEC sys.sp_addextendedproperty
  @name=N'MS_Description', @value=N'BK',
  @level0type=N'SCHEMA', @level0name=N'purchasing',
  @level1type=N'TABLE', @level1name=N'Dim_Supplier',
  @level2type=N'COLUMN', @level2name=N'Supplier_Code'
GO

DECLARE @Region NVARCHAR(50);
SET @Region = 'Strategic';

/* Quarterly volume by supplier
   Requested by: Maria Nilsson
   Jira: PROC-1523 */
SELECT
    s.Supplier_Code AS supplier_id,
    s.Supplier_Name AS supplier_name,
    po.Order_Date,
    SUM(po.Line_Amount) AS total_volume
FROM purchasing.Dim_Supplier s
INNER JOIN purchasing.Fact_Purchase_Order po
    ON s.Supplier_SK = po.Supplier_SK
LEFT JOIN dbo.Dim_Date d
    ON po.Date_SK = d.Date_SK
WHERE d.Fiscal_Year = 2024
    AND s.Supplier_Region = @Region
    AND po.Status = 'Approved'
GROUP BY
    s.Supplier_Code,
    s.Supplier_Name,
    po.Order_Date;
