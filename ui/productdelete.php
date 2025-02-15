<?php
header('Content-Type: application/json');
include_once 'connectdb.php';

// Validate input
$product_id = filter_input(INPUT_POST, 'pidd', FILTER_VALIDATE_INT);

if (!$product_id || $product_id < 1) {
    http_response_code(400);
    echo json_encode(['error' => 'Invalid product ID']);
    exit;
}

try {
    // Check if product exists first
    $check_stmt = $pdo->prepare("SELECT product_id FROM products WHERE product_id = :id");
    $check_stmt->bindParam(':id', $product_id, PDO::PARAM_INT);
    $check_stmt->execute();
    
    if ($check_stmt->rowCount() === 0) {
        http_response_code(404);
        echo json_encode(['error' => 'Product not found']);
        exit;
    }
    
    // Begin transaction
    $pdo->beginTransaction();
    
    // First, delete associated inventory logs
    $delete_logs = $pdo->prepare("DELETE FROM inventory_logs WHERE product_id = :id");
    $delete_logs->bindParam(':id', $product_id, PDO::PARAM_INT);
    $delete_logs->execute();
    
    // Then, delete the product itself
    $delete_stmt = $pdo->prepare("DELETE FROM products WHERE product_id = :id");
    $delete_stmt->bindParam(':id', $product_id, PDO::PARAM_INT);
    
    if ($delete_stmt->execute()) {
        $pdo->commit();
        echo json_encode([
            'success' => true,
            'message' => 'Product deleted successfully'
        ]);
    } else {
        $pdo->rollBack();
        http_response_code(500);
        echo json_encode(['error' => 'Failed to delete product']);
    }
    
} catch(PDOException $e) {
    if ($pdo->inTransaction()) {
        $pdo->rollBack();
    }
    http_response_code(500);
    echo json_encode([
        'error' => 'Database error',
        'details' => $e->getMessage()
    ]);
}
