<?php
require('fpdf/fpdf.php');
include_once 'connectdb.php';

// Validate and sanitize input
$id = filter_input(INPUT_GET, 'id', FILTER_VALIDATE_INT);
if (!$id) {
    die("Invalid invoice ID");
}

// Fetch invoice data using a prepared statement
$invoiceQuery = $pdo->prepare("
    SELECT i.*, e.first_name, e.last_name 
    FROM invoices i
    JOIN employees e ON i.employee_id = e.employee_id
    WHERE i.invoice_id = :id
");
$invoiceQuery->execute([':id' => $id]);
$invoice = $invoiceQuery->fetch(PDO::FETCH_OBJ);

if (!$invoice) {
    die("Invoice not found");
}

// Create PDF object (custom size: 80 x 200 mm)
$pdf = new FPDF('P', 'mm', array(80,200));
$pdf->AddPage();

// ----- Header -----
$pdf->SetFont('Arial', 'B', 16);
$pdf->Cell(60, 8, 'SCHOOL STORE', 0, 1, 'C');

$pdf->SetFont('Arial', 'B', 8);
$pdf->Cell(60, 5, 'Contact: (555) 123-4567', 0, 1, 'C');
$pdf->Cell(60, 5, 'Email: store@school.edu', 0, 1, 'C');
$pdf->Line(7, 28, 72, 28);
$pdf->Ln(2);

// ----- Invoice Information -----
$pdf->SetFont('Arial', 'BI', 8);
$pdf->Cell(20, 4, 'Bill No:', 0, 0);
$pdf->SetFont('Courier', 'BI', 8);
$pdf->Cell(40, 4, $invoice->invoice_id, 0, 1);

$pdf->SetFont('Arial', 'BI', 8);
$pdf->Cell(20, 4, 'Date:', 0, 0);
$pdf->SetFont('Courier', 'BI', 8);
$pdf->Cell(40, 4, $invoice->order_date . ' ' . $invoice->order_time, 0, 1);

$pdf->SetFont('Arial', 'BI', 8);
$pdf->Cell(20, 4, 'Cashier:', 0, 0);
$pdf->SetFont('Courier', 'BI', 8);
$pdf->Cell(40, 4, $invoice->first_name . ' ' . $invoice->last_name, 0, 1);

$pdf->SetFont('Arial', 'BI', 8);
$pdf->Cell(20, 4, 'Payment:', 0, 0);
$pdf->SetFont('Courier', 'BI', 8);
$pdf->Cell(40, 4, $invoice->payment_type, 0, 1);

$pdf->Ln(3);

// ----- Invoice Items (Plain Text List) -----
$pdf->SetFont('Helvetica', '', 8);
$itemsQuery = $pdo->prepare("
    SELECT d.*, p.product_name 
    FROM invoice_details d
    JOIN products p ON d.product_id = p.product_id
    WHERE d.invoice_id = :id
");
$itemsQuery->execute([':id' => $id]);

while ($item = $itemsQuery->fetch(PDO::FETCH_OBJ)) {
    $line  = substr($item->product_name, 0, 20);
    $line .= " | Qty: " . $item->quantity;
    $line .= " | Price: " . number_format($item->unit_price, 2);
    $line .= " | Total: " . number_format($item->total_price, 2);
    $pdf->MultiCell(65, 4, $line, 0, 'L');
}

$pdf->Ln(2);

// ----- Totals (Plain Text) -----
$pdf->SetFont('Courier', 'B', 8);
$pdf->Cell(40, 4, 'SUBTOTAL:', 0, 0, 'L');
$pdf->Cell(25, 4, number_format($invoice->subtotal, 2), 0, 1, 'R');

$discountAmount = $invoice->subtotal * ($invoice->discount / 100);
$pdf->Cell(40, 4, 'DISCOUNT (' . $invoice->discount . '%):', 0, 0, 'L');
$pdf->Cell(25, 4, number_format($discountAmount, 2), 0, 1, 'R');

$pdf->Cell(40, 4, 'TOTAL:', 0, 0, 'L');
$pdf->Cell(25, 4, number_format($invoice->total, 2), 0, 1, 'R');

$pdf->Cell(40, 4, 'PAID:', 0, 0, 'L');
$pdf->Cell(25, 4, number_format($invoice->paid, 2), 0, 1, 'R');

$pdf->Cell(40, 4, 'BALANCE DUE:', 0, 0, 'L');
$pdf->Cell(25, 4, number_format($invoice->due, 2), 0, 1, 'R');

// ----- Footer -----
$pdf->Ln(3);
$pdf->SetX(7);
$pdf->SetFont('Arial', 'I', 6);
$pdf->MultiCell(65, 3, "Thank you for your purchase!\nReturns accepted within 7 days with receipt", 0, 'C');

// Capture PDF as string and encode it for embedding
$pdfString = $pdf->Output('S', 'invoice_' . $invoice->invoice_id . '.pdf');
$base64PDF = base64_encode($pdfString);
?>

<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Invoice #<?= $invoice->invoice_id ?></title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- Optional Bootstrap CSS for styling -->
  <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.5.2/css/bootstrap.min.css">
  <style>
      body { margin: 20px; }
      .pdf-container { width: 100%; height: 90vh; }
  </style>
</head>
<body>
<div class="container">
    <h1 class="mb-3">Invoice #<?= $invoice->invoice_id ?></h1>
    <div class="pdf-container mb-3">
        <!-- Embed the PDF using a data URI -->
        <embed src="data:application/pdf;base64,<?= $base64PDF ?>" type="application/pdf" width="100%" height="100%">
    </div>
    <a href="pos.php" class="btn btn-primary">Go Back</a>
</div>
</body>
</html>
