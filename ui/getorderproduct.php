<!-- getorderproduct.php (POS component) -->
<?php
include_once 'connectdb.php';

$id = $_GET['id'];

try {
    // Prepare query with parameter binding
    $select = $pdo->prepare("
        SELECT 
            d.product_id,
            p.product_name,
            p.barcode,
            d.quantity,
            d.unit_price,
            d.total_price,
            p.stock
        FROM invoice_details d
        INNER JOIN products p ON d.product_id = p.product_id
        WHERE d.invoice_id = :invoice_id
    ");
    
    $select->bindParam(':invoice_id', $id, PDO::PARAM_INT);
    $select->execute();

    $response = $select->fetchAll(PDO::FETCH_ASSOC);

    header('Content-Type: application/json');
    echo json_encode($response);

} catch(PDOException $e) {
    http_response_code(500);
    echo json_encode([
        'error' => 'Database error',
        'message' => $e->getMessage()
    ]);
    exit;
}