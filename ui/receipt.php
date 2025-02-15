<?php
include_once 'connectdb.php';

if(isset($_GET['invoice_id'])) {
    $invoice_id = intval($_GET['invoice_id']);
    
    // Fetch invoice details from database
    $invoice = $pdo->prepare("SELECT * FROM invoices WHERE invoice_id = ?");
    $invoice->execute([$invoice_id]);
    $invoiceData = $invoice->fetch(PDO::FETCH_ASSOC);
    
    // Fetch items
    $items = $pdo->prepare("
        SELECT p.product_name, d.quantity, d.unit_price, d.total_price 
        FROM invoice_details d
        JOIN products p ON d.product_id = p.product_id
        WHERE d.invoice_id = ?
    ");
    $items->execute([$invoice_id]);
    ?>
    <!DOCTYPE html>
    <html>
    <head>
        <title>Receipt #<?= $invoice_id ?></title>
        <style>
            body { font-family: Arial, sans-serif; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 8px; border-bottom: 1px solid #ddd; }
        </style>
    </head>
    <body>
        <h2>School Store Receipt</h2>
        <p>Invoice #: <?= $invoice_id ?></p>
        <p>Date: <?= $invoiceData['order_date'] ?> <?= $invoiceData['order_time'] ?></p>
        
        <table>
            <tr><th>Product</th><th>Qty</th><th>Price</th><th>Total</th></tr>
            <?php while($item = $items->fetch(PDO::FETCH_ASSOC)): ?>
                <tr>
                    <td><?= $item['product_name'] ?></td>
                    <td><?= $item['quantity'] ?></td>
                    <td>₱<?= number_format($item['unit_price'], 2) ?></td>
                    <td>₱<?= number_format($item['total_price'], 2) ?></td>
                </tr>
            <?php endwhile; ?>
        </table>
        
        <h3>Total: ₱<?= number_format($invoiceData['total'], 2) ?></h3>
        <script>window.print();</script>
    </body>
    </html>
    <?php
}