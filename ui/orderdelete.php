<?php
header('Content-Type: application/json');
include_once 'connectdb.php';

$id = $_POST['pidd'];

try {
    $pdo->beginTransaction();

    // 1. Restore product stock
    $selectDetails = $pdo->prepare("
        SELECT product_id, quantity 
        FROM invoice_details 
        WHERE invoice_id = :invoice_id
    ");
    $selectDetails->bindParam(':invoice_id', $id, PDO::PARAM_INT);
    $selectDetails->execute();

    while ($row = $selectDetails->fetch(PDO::FETCH_ASSOC)) {
        $updateStock = $pdo->prepare("
            UPDATE products 
            SET stock = stock + :quantity 
            WHERE product_id = :product_id
        ");
        $updateStock->execute([
            ':quantity' => $row['quantity'],
            ':product_id' => $row['product_id']
        ]);
    }

    // 2. Delete invoice details
    $deleteDetails = $pdo->prepare("
        DELETE FROM invoice_details 
        WHERE invoice_id = :invoice_id
    ");
    $deleteDetails->bindParam(':invoice_id', $id, PDO::PARAM_INT);
    $deleteDetails->execute();

    // 3. Delete main invoice
    $deleteInvoice = $pdo->prepare("
        DELETE FROM invoices 
        WHERE invoice_id = :invoice_id
    ");
    $deleteInvoice->bindParam(':invoice_id', $id, PDO::PARAM_INT);
    $deleteInvoice->execute();

    $pdo->commit();

    echo json_encode(['status' => 'success', 'message' => 'Order deleted successfully']);

} catch (PDOException $e) {
    $pdo->rollBack();
    http_response_code(500);
    echo json_encode([
        'status' => 'error',
        'message' => 'Deletion failed: ' . $e->getMessage()
    ]);
}
