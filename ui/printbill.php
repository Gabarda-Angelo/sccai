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

// Create PDF object and generate the invoice
$pdf = new FPDF('P','mm', array(80,200));
$pdf->AddPage();

// Header
$pdf->SetFont('Arial', 'B', 16);
$pdf->Cell(60, 8, 'SCHOOL STORE', 1, 1, 'C');

$pdf->SetFont('Arial', 'B', 8);
$pdf->Cell(60, 5, 'Contact: (555) 123-4567', 0, 1, 'C');
$pdf->Cell(60, 5, 'Email: store@school.edu', 0, 1, 'C');
$pdf->Line(7, 28, 72, 28);
$pdf->Ln(2);

// Invoice Info
$pdf->SetFont('Arial','BI', 8);
$pdf->Cell(20, 4, 'Bill No:', 0, 0);
$pdf->SetFont('Courier','BI', 8);
$pdf->Cell(40, 4, $invoice->invoice_id, 0, 1);

$pdf->SetFont('Arial','BI', 8);
$pdf->Cell(20, 4, 'Date:', 0, 0);
$pdf->SetFont('Courier','BI', 8);
$pdf->Cell(40, 4, $invoice->order_date . ' ' . $invoice->order_time, 0, 1);

$pdf->SetFont('Arial','BI', 8);
$pdf->Cell(20, 4, 'Cashier:', 0, 0);
$pdf->SetFont('Courier','BI', 8);
$pdf->Cell(40, 4, $invoice->first_name . ' ' . $invoice->last_name, 0, 1);

// Table Header
$pdf->SetX(7);
$pdf->SetFont('Courier', 'B', 8);
$pdf->Cell(34,5, 'PRODUCT', 1, 0, 'C');
$pdf->Cell(11,5, 'QTY', 1, 0, 'C');
$pdf->Cell(14,5, 'PRICE', 1, 0, 'C');
$pdf->Cell(14,5, 'TOTAL', 1, 1, 'C');

// Invoice Items
$itemsQuery = $pdo->prepare("
    SELECT d.*, p.product_name 
    FROM invoice_details d
    JOIN products p ON d.product_id = p.product_id
    WHERE d.invoice_id = :id
");
$itemsQuery->execute([':id' => $id]);

while ($item = $itemsQuery->fetch(PDO::FETCH_OBJ)) {
    $pdf->SetX(7);
    $pdf->SetFont('Helvetica','', 8);
    $pdf->Cell(34,5, substr($item->product_name, 0, 20), 1, 0, 'L');
    $pdf->Cell(11,5, $item->quantity, 1, 0, 'C');
    $pdf->Cell(14,5, number_format($item->unit_price, 2), 1, 0, 'C');
    $pdf->Cell(14,5, number_format($item->total_price, 2), 1, 1, 'C');
}

// Calculations
$discountAmount = $invoice->subtotal * ($invoice->discount / 100);

// Totals
$pdf->SetX(7);
$pdf->SetFont('Courier','B',8);
$pdf->Cell(45,5,'SUBTOTAL',1,0,'C');
$pdf->Cell(20,5, number_format($invoice->subtotal,2), 1, 1, 'C');

$pdf->SetX(7);
$pdf->Cell(45,5, 'DISCOUNT ('.$invoice->discount.'%)', 1,0,'C');
$pdf->Cell(20,5, number_format($discountAmount,2), 1, 1, 'C');

$pdf->SetX(7);
$pdf->Cell(45,5,'TOTAL',1,0,'C');
$pdf->Cell(20,5, number_format($invoice->total,2), 1, 1, 'C');

$pdf->SetX(7);
$pdf->Cell(45,5,'PAID',1,0,'C');
$pdf->Cell(20,5, number_format($invoice->paid,2), 1, 1, 'C');

$pdf->SetX(7);
$pdf->Cell(45,5,'BALANCE DUE',1,0,'C');
$pdf->Cell(20,5, number_format($invoice->due,2), 1, 1, 'C');

// Footer
$pdf->Ln(3);
$pdf->SetX(7);
$pdf->SetFont('Arial','I',6);
$pdf->MultiCell(65,3, "Thank you for your purchase!\nReturns accepted within 7 days with receipt", 0, 'C');

// Instead of outputting the PDF directly, capture the PDF data as a string
$pdfString = $pdf->Output('S', 'invoice_'.$id.'.pdf');
$base64PDF = base64_encode($pdfString);
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Invoice #<?= $invoice->invoice_id ?></title>
    <!-- Include Bootstrap CSS if not already available -->
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
    <!-- Go Back Button (adjust the href as needed, e.g., pos.php or orderlist.php) -->
    <a href="pos.php" class="btn btn-primary">Go Back</a>
</div>
</body>
</html>
